"""Раздел «Статистика»: вакансии, разборы и отклики по дням, неделям и месяцам — из файлов профиля, без модели.

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
from .files import decision_word

STEPS = {"day": 30, "week": 12, "month": 12}       # шаг → сколько периодов показываем
METRICS = [("added", "Добавлено"), ("analyzed", "Разобрано ИИ"),
           ("applied", "Откликов"), ("answered", "Ответов"), ("rejected", "Отказов"), ("interview", "Интервью"), ("offer", "Офферов")]
ANSWER = ("answered", "hr", "manager", "final", "offer", "rejected")   # любой отклик работодателя — ответ
INTERVIEW = ("hr", "manager", "final", "offer")
WAIT_DAYS = 7                                       # отклик без ответа дольше — в список «ждут ответа»
GOOD = 7                                            # «хорошая» оценка — для воронки
KINDS = ("employer", "agency", "hidden")            # кто разместил вакансию — столбики «По периодам» по частям


ANSWERS = ("да", "возможно", "нет")

def answer(text):
    """Ответ «откликаться» одним словом: «да, но с оговорками» и «возможно» — «возможно»; пусто — нет ответа."""
    t = (text or "").strip().lower()
    return "возможно" if t.startswith("возм") else decision_word(t)

def answers(rows):
    model = [answer(r.get("decision")) if r.get("score") is not None else "" for r in rows]
    mine = [answer(r.get("my_decision")) for r in rows]
    pair = [(m, y) for m, y in zip(model, mine) if m and y]
    return {"ans_model": [model.count(a) for a in ANSWERS], "ans_mine": [mine.count(a) for a in ANSWERS],
            "ans_matrix": [[pair.count((m, y)) for y in ANSWERS] for m in ANSWERS], "ans_both": len(pair)}

BUCKETS = (("7–10", 7, 10), ("5–6", 5, 6), ("1–4", 1, 4))

def _bucket(score):
    if score is None:
        return None
    v = min(max(round(score), 1), 10)
    return next(label for label, lo, hi in BUCKETS if lo <= v <= hi)

def outcomes(evs):
    """Чем кончились отклики (все отклики профиля): по оценке модели, по вашей оценке и по вашему ответу.
    В каждой группе: откликов, ответили, интервью, отказ."""
    sent = [(r, e) for r, e in evs if e["applied"]]
    def group(label, items):
        return {"label": label, "applied": len(items), **{k: sum(1 for _, e in items if e[k]) for k in ("answered", "interview", "rejected")}}
    def by(key, none_label):
        out = [group(label, [x for x in sent if _bucket(x[0].get(key)) == label]) for label, *_ in BUCKETS]
        return out + [group(none_label, [x for x in sent if x[0].get(key) is None])]
    return {"model": by("score", "без оценки"), "mine": by("my_score", "не оценено вами"),
            "answer": [group(a.capitalize(), [x for x in sent if answer(x[0].get("my_decision")) == a]) for a in ANSWERS]
                      + [group("нет вашего ответа", [x for x in sent if not answer(x[0].get("my_decision"))])]}

def agreement(rows, today, edits=(), weeks=12):
    """Модель и вы по неделям разбора (последнего): где есть обе оценки — совпало точно, ±1 балл, совпал ответ.
    edits — даты правок критериев, чтобы видеть, стала ли модель точнее после них."""
    start = today - timedelta(days=today.weekday() + 7 * (weeks - 1))
    out = []
    for i in range(weeks):
        a = start + timedelta(days=7 * i)
        b = a + timedelta(days=6)
        both = [r for r in rows if r.get("score") is not None and r.get("my_score") is not None
                and a.isoformat() <= (r.get("scored_on") or "")[:10] <= b.isoformat()]
        ans = [r for r in both if answer(r.get("decision")) and answer(r.get("my_decision"))]
        out.append({"start": a.isoformat(), "end": b.isoformat(), "both": len(both),
                    "same": sum(1 for r in both if round(r["score"]) == round(r["my_score"])),
                    "near": sum(1 for r in both if abs(round(r["score"]) - round(r["my_score"])) <= 1),
                    "ans_both": len(ans), "ans_same": sum(1 for r in ans if answer(r["decision"]) == answer(r["my_decision"])),
                    "edits": sorted({d[:10] for d in edits if a.isoformat() <= d[:10] <= b.isoformat()})})
    return out

def engine(r):
    """Кто оценивал вакансию: локальная модель, облачный GigaChat или никто (не разобрана, «Без модели»)."""
    if not r.get("analyzed") or r.get("stage") == "none" or r.get("score") is None:
        return "none"
    return "cloud" if re.match(r"gigachat", r.get("model") or "", re.I) else "local"


def engines(rows):
    """По моделям: сколько вакансий, какие названия моделей, быстрая оценка или полный разбор, решения,
    насколько оценки совпали с вашими — по вакансиям, где есть обе."""
    out = {k: {"key": k, "count": 0, "names": {}, "short": 0, "full": 0, "yes": 0, "maybe": 0, "no": 0,
               "both": 0, "same": 0, "near": 0} for k in ("local", "cloud", "none")}
    for r in rows:
        e = out[engine(r)]
        e["count"] += 1
        if e["key"] == "none":
            continue
        if r.get("model"):
            e["names"][r["model"]] = e["names"].get(r["model"], 0) + 1
        e["short" if r.get("stage") == "short" else "full"] += 1
        d = answer(r.get("decision"))
        e["yes"] += d == "да"; e["maybe"] += d == "возможно"; e["no"] += d == "нет"
        if r.get("my_score") is not None:
            diff = abs(round(r["score"]) - round(r["my_score"]))
            e["both"] += 1; e["same"] += diff == 0; e["near"] += diff <= 1
    for e in out.values():
        e["names"] = sorted(e["names"], key=lambda k: -e["names"][k])
    return list(out.values())


def kind(r):
    """Работодатель, кадровое агентство или работодатель скрыт — для столбиков по периодам."""
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


def compute(rows, step="week", today=None, status_names=None, criteria_edits=()):
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
    steps = [("Добавлено", lambda r, e: True),
             ("Разобрано ИИ", lambda r, e: e["analyzed"]),
             (f"Оценка {GOOD}+", lambda r, e: (r.get("score") or 0) >= GOOD),
             ("Откликнулся", lambda r, e: e["applied"]),
             ("Ответили", lambda r, e: e["answered"]),
             ("Интервью", lambda r, e: e["interview"]),
             ("Оффер", lambda r, e: e["offer"])]
    funnel = []
    for label, ok in steps:                         # каждый шаг — и по частям KINDS, как столбики по периодам
        parts = dict.fromkeys(KINDS, 0)
        for r, e in cohort:
            if ok(r, e):
                parts[kind(r)] += 1
        funnel.append({"label": label, "count": sum(parts.values()), "by_kind": parts})
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
    # Оценки: сколько вакансий получили 1…10 у модели и у вас; где обе — насколько модель расходится с вами
    def bins(vals):
        out = [0] * 10
        for v in vals:
            out[min(max(round(v), 1), 10) - 1] += 1
        return out
    model = [r["score"] for r in rows if r.get("score") is not None]
    mine = [r["my_score"] for r in rows if r.get("my_score") is not None]
    both = [(r["score"], r["my_score"]) for r in rows if r.get("score") is not None and r.get("my_score") is not None]
    scores_all = {"model": bins(model), "mine": bins(mine),
                  "model_avg": round(mean(model), 1) if model else None, "mine_avg": round(mean(mine), 1) if mine else None,
                  "both": len(both), "diff_avg": round(mean(abs(m - y) for m, y in both), 1) if both else None,
                  "higher": sum(1 for m, y in both if round(m) > round(y)),
                  "lower": sum(1 for m, y in both if round(m) < round(y)),
                  # разница «модель − вы» от −9 до +9: сколько вакансий с каждой
                  "diffs": [sum(1 for m, y in both if round(m) - round(y) == d) for d in range(-9, 10)],
                  # ответы «откликаться»: да / возможно / нет у модели и у вас; где оба — кто что ответил (строка — модель)
                  **answers(rows)}
    names = dict(status_names or [])
    now = {}                                         # по статусам: всего, закрытых на сайте, с флагом
    for r in rows:
        c = now.setdefault(r.get("status", "new"), {"count": 0, "closed": 0, "flagged": 0})
        c["count"] += 1
        c["closed"] += bool((r.get("actual") or {}).get("closed"))
        c["flagged"] += bool(r.get("flag"))
    return {
        "step": step, "today": today.isoformat(), "start": a.isoformat(), "end": b.isoformat(),
        "metrics": [{"key": k, "label": l} for k, l in METRICS],
        "series": series, "totals": totals, "periods_full": round(full, 2),
        "funnel": funnel,
        "score": {"avg": round(mean(scores), 1) if scores else None, "good": sum(1 for s in scores if s >= GOOD),
                  "count": len(scores)},
        "speed": speed, "waiting": waiting, "wait_days": WAIT_DAYS,
        "letters": letters,
        "scores": scores_all,
        "engines": engines(rows),
        "outcomes": outcomes(evs),
        "agreement": agreement(rows, today, criteria_edits),
        "sources": sorted(sources.values(), key=lambda s: (-s["added"], s["source"])),
        "statuses": [{"key": k, "label": names.get(k, k), **now.get(k, {"count": 0, "closed": 0, "flagged": 0})}
                     for k in names],                # все статусы, и пустые
        "flags": sum(1 for r in rows if r.get("flag")),
        "total_vacancies": len(rows),
    }
