"""Раздел «Статистика» (#55): вакансии, разборы и отклики по дням, неделям и месяцам — из файлов профиля, без модели.

Даты событий берутся из строк таблицы (app.vacancy_rows):
    добавлено — «Сохранено»; разобрано моделью — первый разбор (история разборов или паспорт);
    отклик, ответ, интервью, оффер — первые даты этапов воронки. Поздний этап подразумевает ранние: вакансия,
    которой сразу поставили «Интервью с HR» или «Отказ», — это и отклик (так бывает, когда этапы начали вести
    не с начала). Скорость ответа — только по вакансиям с настоящей отметкой «Откликнулся», иначе выйдет «0 дней».
"""
import re
from datetime import date, timedelta
from statistics import mean

from .contacts import company_key

STEPS = {"day": 30, "week": 12, "month": 12}       # шаг → сколько периодов показываем
METRICS = [("added", "Добавлено"), ("analyzed", "Разобрано ИИ"),
           ("applied", "Откликов"), ("answered", "Ответов"), ("rejected", "Отказов"), ("interview", "Интервью"), ("offer", "Офферов")]
ANSWER = ("answered", "hr", "manager", "final", "offer", "rejected")   # любой отклик работодателя — ответ
INTERVIEW = ("hr", "manager", "final", "offer")
WAIT_DAYS = 7                                       # отклик без ответа дольше — в список «ждут ответа»
GOOD = 7                                            # «хорошая» оценка — для воронки
KINDS = ("employer", "agency", "hidden")            # кто разместил вакансию — столбики «По периодам» по частям


def kind(r):
    """Работодатель, кадровое агентство (#2) или работодатель скрыт — для столбиков по периодам."""
    if r.get("agency"):
        return "agency"
    key = company_key(r.get("company", ""))
    return "hidden" if not key or re.search(r"anonim|neukazan", key) else "employer"


def _first(history, stages):
    return min((h["date"] for h in history if h["stage"] in stages), default="")


def events(r):
    """Даты событий вакансии (строка таблицы): {метрика: "2026-10-20" или ""}."""
    f = r.get("funnel") or {"history": [], "statuses": []}
    h = f["history"]
    return {"added": r.get("added_key", ""), "analyzed": r.get("analyzed_on", "") if r.get("analyzed") and r.get("stage") != "none" else "",
            "applied": min((x["date"] for x in h), default=""), "applied_mark": _first(h, ("applied",)),
            "answered": _first(h, ANSWER),
            "interview": _first(h, INTERVIEW), "offer": _first(h, ("offer",)), "rejected": _first(h, ("rejected",))}


def _add_months(d, k):
    m = d.month - 1 + k
    return date(d.year + m // 12, m % 12 + 1, 1)


def periods(step, today, back=0):
    """Периоды диапазона, старые первыми: [(начало, конец включительно, доля прошедшего)]. back=1 — прошлый
    такой же диапазон (для сравнения). Текущий период неполный: доля — сколько его дней уже прошло."""
    count = STEPS[step]
    if step == "day":
        last = today - timedelta(days=count * back)
        return [(d, d, 1.0) for d in (last - timedelta(days=i) for i in range(count - 1, -1, -1))]
    if step == "week":
        start = today - timedelta(days=today.weekday()) - timedelta(weeks=count * back)
        out = [(start - timedelta(weeks=i), start - timedelta(weeks=i) + timedelta(days=6)) for i in range(count - 1, -1, -1)]
    else:
        start = _add_months(today.replace(day=1), -count * back)
        out = [(_add_months(start, -i), _add_months(start, -i + 1) - timedelta(days=1)) for i in range(count - 1, -1, -1)]
    return [(a, b, min(1.0, ((today - a).days + 1) / ((b - a).days + 1)) if a <= today <= b else 1.0) for a, b in out]


def _count(evs, key, a, b):
    a, b = a.isoformat(), b.isoformat()
    return sum(1 for e in evs if e[key] and a <= e[key] <= b)


def _split(evs, key, a, b):
    """То же число, разложенное по KINDS: {"employer": 3, "agency": 1, "hidden": 0}."""
    a, b = a.isoformat(), b.isoformat()
    out = dict.fromkeys(KINDS, 0)
    for r, e in evs:
        if e[key] and a <= e[key] <= b:
            out[kind(r)] += 1
    return out


def _days(x, y):
    return (date.fromisoformat(y) - date.fromisoformat(x)).days


def compute(rows, step="week", today=None, status_names=None):
    """Всё для раздела «Статистика»: ряды по периодам, итоги и средние, воронка, скорость, ждущие ответа,
    источники, статусы сейчас."""
    if step not in STEPS:
        step = "week"
    today = today or date.today()
    evs = [(r, events(r)) for r in rows]
    only = [e for _, e in evs]
    ps = periods(step, today)
    series = [{"start": a.isoformat(), "end": b.isoformat(), "partial": part < 1,
               **{k: _count(only, k, a, b) for k, _ in METRICS},
               "by_kind": {k: _split(evs, k, a, b) for k, _ in METRICS}} for a, b, part in ps]
    full = sum(part for *_, part in ps)              # неполный текущий период не занижает среднее
    prev = periods(step, today, back=1)
    a, b = ps[0][0], ps[-1][1]
    totals = {k: {"total": sum(s[k] for s in series), "avg": round(sum(s[k] for s in series) / full, 1),
                  "prev": _count(only, k, prev[0][0], prev[-1][1])} for k, _ in METRICS}

    # Воронка — по вакансиям, добавленным в диапазоне: докуда каждая дошла (в любое время)
    cohort = [(r, e) for r, e in evs if e["added"] and a.isoformat() <= e["added"] <= b.isoformat()]
    funnel = [("Добавлено", len(cohort)),
              ("Разобрано ИИ", sum(1 for _, e in cohort if e["analyzed"])),
              (f"Оценка {GOOD}+", sum(1 for r, _ in cohort if (r.get("score") or 0) >= GOOD)),
              ("Откликнулся", sum(1 for _, e in cohort if e["applied"])),
              ("Ответили", sum(1 for _, e in cohort if e["answered"])),
              ("Интервью", sum(1 for _, e in cohort if e["interview"])),
              ("Оффер", sum(1 for _, e in cohort if e["offer"]))]
    scores = [r["score"] for r, _ in cohort if r.get("score") is not None]

    # Скорость — по всем откликам профиля: в диапазоне их обычно слишком мало для средних
    def avg_days(pairs):
        days = [_days(x, y) for x, y in pairs if x and y and y >= x]
        return {"days": round(mean(days), 1) if days else None, "count": len(days)}
    marked = [e for _, e in evs if e["applied_mark"]]
    speed = {"to_apply": avg_days((e["added"], e["applied_mark"]) for e in marked),
             "to_answer": avg_days((e["applied_mark"], e["answered"]) for e in marked),
             "to_interview": avg_days((e["applied_mark"], e["interview"]) for e in marked)}
    waiting = sorted(({"n": r["n"], "title": r["title"], "company": r["company"], "applied": e["applied"],
                       "days": _days(e["applied"], today.isoformat())}
                      for r, e in evs if e["applied"] and not e["answered"] and r.get("status") != "no"
                      and (r.get("funnel") or {}).get("stage") != "silent"
                      and _days(e["applied"], today.isoformat()) >= WAIT_DAYS), key=lambda w: -w["days"])

    sources = {}
    for r, e in cohort:
        s = sources.setdefault(r.get("source") or "Вручную", {"source": r.get("source") or "Вручную",
                                                             "added": 0, "applied": 0, "answered": 0, "interview": 0})
        s["added"] += 1
        for k in ("applied", "answered", "interview"):
            s[k] += bool(e[k])
    # Отклики с сопроводительным письмом и без: письмо — по отметке «Отправлено» (копия в «Артефактах»)
    sent = [(r, e) for r, e in evs if e["applied"] and a.isoformat() <= e["applied"] <= b.isoformat()]
    letters = [{"letter": flag, "applied": len(group), **{k: sum(1 for _, e in group if e[k])
                                                           for k in ("answered", "rejected", "interview")}}
               for flag, group in ((True, [x for x in sent if x[0].get("cover_sent")]),
                                   (False, [x for x in sent if not x[0].get("cover_sent")]))]
    names = dict(status_names or [])
    now = {}
    for r in rows:
        now[r.get("status", "new")] = now.get(r.get("status", "new"), 0) + 1
    return {
        "step": step, "today": today.isoformat(), "start": a.isoformat(), "end": b.isoformat(),
        "metrics": [{"key": k, "label": l} for k, l in METRICS],
        "series": series, "totals": totals, "periods_full": round(full, 2),
        "funnel": [{"label": l, "count": c} for l, c in funnel],
        "score": {"avg": round(mean(scores), 1) if scores else None, "good": sum(1 for s in scores if s >= GOOD),
                  "count": len(scores)},
        "speed": speed, "waiting": waiting, "wait_days": WAIT_DAYS,
        "letters": letters,
        "sources": sorted(sources.values(), key=lambda s: (-s["added"], s["source"])),
        "statuses": [{"key": k, "label": names.get(k, k), "count": now.get(k, 0)} for k in names if now.get(k)],
        "flags": sum(1 for r in rows if r.get("flag")),
        "total_vacancies": len(rows),
    }
