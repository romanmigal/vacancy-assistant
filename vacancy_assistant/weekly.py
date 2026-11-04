"""«Итоги недели»: где затык — мало подходящих вакансий, мало откликов, ответов или интервью — и прогресс.

Неделя — с понедельника по воскресенье: прошлая (по умолчанию — её итоги показывает плашка в начале недели) или
текущая. Рядом — неделя до неё и всё время. Без модели: числа — из файлов профиля (события — как в «Статистике»,
stats.events), найденное поиском hh — из просмотрено.txt, причины «нет» — нарушенные критерии из разборов.
Вывод — правилами: какой шаг воронки проседает и что с этим делать.
"""
import collections
from datetime import date, timedelta

from . import stats
from .hh import plural
from .textio import read_text

GOOD = stats.GOOD
SEARCH_MARKS = ("взята", "отсеяна")         # пометки поиска hh в просмотрено.txt; «из письма», «по ссылке» — не поиск
METRICS = [("found", "Найдено поиском hh"), ("title_ok", "Прошло отбор по названию"), ("added", "Добавлено"),
           ("analyzed", "Разобрано ИИ"), ("good", f"Оценка {GOOD}+"), ("applied", "Откликов"), ("answered", "Ответов"),
           ("rejected", "Отказов"), ("interview", "Интервью"), ("offer", "Офферов")]
ADDED_BOTH = "Добавлено: поиском hh и вручную"     # с поиском «Добавлено» легко принять за взятое поиском
STEP_NAMES = {"analyzed": "Разобрано", "good": f"Оценка {GOOD}+", "applied": "Отклик", "answered": "Ответ",
              "interview": "Интервью", "offer": "Оффер"}
STEPS = [("analyzed", "good"), ("good", "applied"), ("applied", "answered"), ("answered", "interview"), ("interview", "offer")]
TOP = 5
EXAMPLES = 3


def bounds(which="last", today=None):
    """(понедельник, воскресенье) прошлой (last) или текущей (this) недели."""
    today = today or date.today()
    monday = today - timedelta(days=today.weekday())
    if which != "this":
        monday -= timedelta(weeks=1)
    return monday, monday + timedelta(days=6)


def _seen(profile):
    """Строки поиска hh из просмотрено.txt: [(дата ISO, пометка, название)]."""
    if not profile.seen.exists():
        return []
    out = []
    for line in read_text(profile.seen).splitlines():
        parts = line.split("\t")
        if len(parts) < 4 or parts[2] not in SEARCH_MARKS:
            continue
        d = parts[1].split(".")
        if len(d) == 3:
            out.append((f"{d[2]}-{d[1]}-{d[0]}", parts[2], parts[3]))
    return out


def _in(day, a, b):
    return bool(day) and a <= day <= b


def counts(evs, seen, a, b):
    """Числа за период [a, b] (строки ISO; None — всё время)."""
    inside = (lambda d: bool(d)) if a is None else (lambda d: _in(d, a, b))
    out = {k: sum(1 for _, e in evs if inside(e[k])) for k in ("added", "analyzed", "applied", "answered", "rejected",
                                                               "interview", "offer")}
    out["good"] = sum(1 for r, e in evs if inside(e["analyzed"]) and (r.get("score") or 0) >= GOOD)
    out["found"] = sum(1 for d, *_ in seen if inside(d))
    out["title_ok"] = sum(1 for d, mark, _ in seen if inside(d) and mark == "взята")
    return out


def conversions(c):
    return [{"from": x, "to": y, "label": f"{STEP_NAMES[x]} → {STEP_NAMES[y]}",
             "pct": round(c[y] / c[x] * 100) if c[x] else None} for x, y in STEPS]


def reasons(evs, a, b):
    """Нарушенные критерии у вакансий, разобранных в период: [{"name", "count"}], частые первыми."""
    got = collections.Counter(v["name"] or f"К{v['n']}" for r, e in evs if (a is None or _in(e["analyzed"], a, b))
                              for v in r.get("violations") or [])
    return [{"name": k, "count": n} for k, n in got.most_common(TOP)]


def title_drops(profile, seen, a, b):
    """Отсеянные по названию в период, по причинам (по нынешним правилам): [{"reason", "count", "examples"}]."""
    by = collections.defaultdict(list)
    for d, mark, title in seen:
        if mark == "отсеяна" and _in(d, a, b):
            by[profile.title_reason(title) or "теперь подходит"].append(title)
    return [{"reason": k, "count": len(v), "examples": list(dict.fromkeys(v))[:EXAMPLES]}
            for k, v in sorted(by.items(), key=lambda kv: -len(kv[1]))][:TOP]


def advice(week, prev, total, why, drops, waiting):
    """Вывод правилами: [{"kind": "good" | "warn", "text"}]."""
    out = []
    say = lambda kind, text: out.append({"kind": kind, "text": text})
    if not week["added"] and not week["found"]:
        say("warn", "За неделю не добавлено ни одной вакансии. Загрузите письма Автопоиска hh или вакансии по ссылкам — "
                    "раз в день достаточно.")
    if week["found"] >= 20 and not week["title_ok"]:
        top = f" Чаще всего — {drops[0]['reason']}." if drops else ""
        say("warn", f"Из {week['found']} найденных поиском ни одна не прошла отбор по названию.{top} "
                    "Если среди отсеянных есть подходящие — поправьте отбор в «Редактировать профиль».")
    if week["analyzed"] >= 5 and not week["good"]:
        top = f" Чаще всего не выполнялся критерий «{why[0]['name']}»." if why else ""
        say("warn", f"Из {week['analyzed']} разобранных ни одной с оценкой {GOOD}+.{top} Проверьте поисковые запросы "
                    "или критерии — возможно, они слишком строгие.")
    if week["good"] >= 3 and week["applied"] < week["good"] / 2:
        say("warn", f"{plural(week['good'], 'вакансия', 'вакансии', 'вакансий')} с оценкой {GOOD}+, "
                    f"а откликов {week['applied']}. Откликайтесь чаще — и ставьте этап «Откликнулся»: "
                    "по нему программа учится, что вам интересно.")
    if total["applied"] >= 10 and total["answered"] < total["applied"] * 0.15:
        say("warn", f"За всё время ответили на {total['answered']} из {total['applied']} откликов. Загляните в «Резюме "
                    "против рынка» — каких слов и требований не хватает резюме — и пишите сопроводительные письма.")
    if total["answered"] >= 5 and not total["interview"]:
        say("warn", f"Ответов {total['answered']}, а интервью пока нет. Посмотрите, что пишут в отказах, — и в каких "
                    "вакансиях оценка «Могу» ниже.")
    if waiting:
        say("warn", f"{plural(waiting, 'отклик ждёт', 'отклика ждут', 'откликов ждут')} ответа дольше "
                    f"{stats.WAIT_DAYS} дней. Напомните о себе или отметьте этап «Не ответили».")
    if week["applied"] > prev["applied"] and prev["applied"]:
        say("good", f"Откликов больше, чем неделей раньше: {week['applied']} против {prev['applied']}.")
    if week["interview"]:
        say("good", f"Интервью за неделю: {week['interview']}. Не забудьте записать договорённости в «Артефакты».")
    if week["offer"]:
        say("good", f"Офферов за неделю: {week['offer']}!")
    if not out and week["applied"]:
        say("good", "Всё идёт ровно: вакансии находятся, отклики уходят. Так держать.")
    return out


def compute(profile, rows, which="last", today=None):
    """Всё для окна «Итоги недели»."""
    today = today or date.today()
    mon, sun = bounds(which, today)
    a, b = mon.isoformat(), sun.isoformat()
    pa, pb = (mon - timedelta(weeks=1)).isoformat(), (mon - timedelta(days=1)).isoformat()
    evs = [(r, stats.events(r)) for r in rows]
    seen = _seen(profile)
    week, prev, total = counts(evs, seen, a, b), counts(evs, seen, pa, pb), counts(evs, seen, None, None)
    why, drops = reasons(evs, a, b), title_drops(profile, seen, a, b)
    waiting = len(stats.compute(rows, "week", today)["waiting"])
    search = bool(seen)
    return {
        "which": "this" if which == "this" else "last", "start": a, "end": b, "today": today.isoformat(),
        "partial": which == "this",
        "metrics": [{"key": k, "label": ADDED_BOTH if search and k == "added" else l}
                    for k, l in METRICS if search or k not in ("found", "title_ok")],
        "week": week, "prev": prev, "total": total,
        "conversions": conversions(total),
        "reasons": why, "reasons_total": reasons(evs, None, None),
        "title_drops": drops, "waiting": waiting,
        "advice": advice(week, prev, total, why, drops, waiting),
    }


def markdown(rep):
    """Итоги недели в Markdown — обсудить с карьерным консультантом или другом."""
    d = lambda iso: f"{iso[8:10]}.{iso[5:7]}.{iso[:4]}"
    lines = [f"# Итоги недели: {d(rep['start'])} — {d(rep['end'])}" + (" (неделя идёт)" if rep["partial"] else ""), "",
             "| | Неделя | Неделей раньше | Всё время |", "|---|---:|---:|---:|"]
    lines += [f"| {m['label']} | {rep['week'][m['key']]} | {rep['prev'][m['key']]} | {rep['total'][m['key']]} |"
              for m in rep["metrics"]]
    lines += ["", "## Переходы за всё время", ""]
    lines += [f"- {c['label']}: {'—' if c['pct'] is None else str(c['pct']) + '%'}"
              for c in rep["conversions"]]
    if rep["reasons"]:
        lines += ["", "## Что чаще всего не подходило", ""] + [f"- {x['name']}: {x['count']}" for x in rep["reasons"]]
    if rep["title_drops"]:
        lines += ["", "## Отсеяно по названию", ""] + [f"- {x['reason']}: {x['count']}" for x in rep["title_drops"]]
    if rep["advice"]:
        lines += ["", "## Вывод", ""] + [f"- {x['text']}" for x in rep["advice"]]
    return "\n".join(lines)
