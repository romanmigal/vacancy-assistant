"""Расхождения со своей оценкой для «Резюме против рынка» (#80): вакансии, которые вы сами считаете подходящими,
а модель отвергла, — что прокачать.

Выборка — вакансии со своей оценкой не раньше выбранной даты. Главное — «модель — нет, вы — да или возможно»: по
резюме и «Дополнительно о себе» модель не видит того, что нужно работодателю. Ниже — наоборот (модель переоценивает —
это скорее к критериям). Правка резюме и «о себе» в окне — с пересчётом отмеченных вакансий и «Вернуть как было»;
последний пересчёт — в рынок.json (market.FILE), рядом с подсказкой модели.
"""
from datetime import date, datetime, timedelta

from . import analysis, answer, setup
from .errors import AssistantError
from .files import analysis_body, decision_yes, numbered_files
from .fix import _outcome
from .textio import read_json, read_text, write_json, write_text

FILE = "рынок.json"          # общий с market: {"history", "advice", "recheck": {date, changed, old, results, items}}
DEFAULT_DAYS = 30


def default_since(today=None):
    return ((today or date.today()) - timedelta(days=DEFAULT_DAYS)).isoformat()


def _failed(profile, path):
    """Требования с ❌ и нарушенные критерии из разбора вакансии."""
    from .market import _requirement
    result = profile.results / path.name
    if not result.exists():
        return [], []
    p = answer.parse(analysis_body(read_text(result)))
    return ([_requirement(q["text"]) for q in p["requirements"] if not q["ok"]],
            [{"k": c["k"], "mark": c["mark"], "text": c["text"]} for c in p["criteria"] if c["mark"] == "❌"])


def discrepancies(profile, rows, since=None):
    """Свои оценки с даты since: сколько, совпало, ждут разбора; расхождения — модель «нет» / вы «да» (under) и наоборот (over)."""
    since = since or default_since()
    files = numbered_files(profile.vacancies)
    rated = [r for r in rows if r.get("my_decision") and (r.get("my_date") or "") >= since and r["n"] in files]
    under, over, same, waiting = [], [], 0, 0
    for r in rated:
        model_yes = decision_yes(r.get("decision")) if r.get("analyzed") else None
        if model_yes is None:
            waiting += 1
            continue
        mine_yes = r["my_decision"] != "нет"
        if mine_yes == model_yes:
            same += 1
            continue
        failed, criteria = _failed(profile, files[r["n"]])
        item = {"n": r["n"], "title": r["title"], "company": r["company"],
                "mine": {k: r.get(f"my_{k}") for k in ("score", "can", "want", "decision", "date", "reason")},
                "model": {k: r.get(k) for k in ("score", "can", "want", "decision", "stage")},
                "failed": failed, "criteria": criteria}
        (under if mine_yes else over).append(item)
    order = lambda v: (-(v["mine"]["score"] or 0), v["n"])
    return {"since": since, "rated": len(rated), "same": same, "waiting": waiting,
            "under": sorted(under, key=order), "over": sorted(over, key=order)}


def recheck(profile, ns, data, log, ask=None):
    """Задача «Сохранить и пересчитать»: правки резюме и «о себе» — в профиль, затем новый разбор вакансий ns.
    Прежние тексты и разборы запоминаются — «Вернуть как было»."""
    files = numbered_files(profile.vacancies)
    ns = [n for n in ns if n in files]
    if not ns:
        raise AssistantError("Отметьте вакансии, которые пересчитать.")
    old = setup.answers_from_profile(profile)
    edits = {k: data[k] for k in ("resume", "facts") if data.get(k) is not None
             and " ".join(str(data[k]).split()) != " ".join(str(old.get(k) or "").split())}
    if "resume" in edits and not old["resume_editable"]:
        raise AssistantError("Резюме лежит во внешнем файле — поправьте его там или в «Параметры → Резюме».")
    if "resume" in edits and not edits["resume"].strip():
        raise AssistantError("Резюме не может быть пустым.")
    before = {}
    for n in ns:
        result = profile.results / files[n].name
        before[n] = read_text(result) if result.exists() else ""
    if edits:
        log("Сохраняю: " + ", ".join({"resume": "резюме", "facts": "«о себе»"}[k] for k in edits))
        setup.update_profile(profile, edits, log=lambda *_: None)
    items = []
    for i, n in enumerate(ns, 1):
        log(f"[{i}/{len(ns)}] {files[n].stem}")
        analysis.full_analysis(profile, files[n], log=log, ask=ask)
        after = read_text(profile.results / files[n].name)
        items.append({"n": n, "before": _outcome(before[n]), "after": _outcome(after)})
    state = {"date": datetime.now().strftime("%Y-%m-%d %H:%M"), "changed": sorted(edits),
             "old": {k: old.get(k) or "" for k in edits}, "results": {str(n): before[n] for n in ns}, "items": items}
    data = read_json(profile.dir / FILE, {})
    data["recheck"] = state
    write_json(profile.dir / FILE, data)
    better = sum(1 for it in items if decision_yes(it["after"]["decision"]) and not decision_yes(it["before"]["decision"]))
    log(f"Пересчитано {len(items)}: решение стало «да» у {better}")
    return state


def undo(profile):
    """«Вернуть как было»: прежние резюме, «о себе» и прежние разборы пересчитанных вакансий."""
    data = read_json(profile.dir / FILE, {})
    state = data.get("recheck")
    if not state:
        raise AssistantError("Нечего возвращать: пересчёта не было.")
    if state["old"]:
        setup.update_profile(profile, state["old"], log=lambda *_: None)
    files = numbered_files(profile.vacancies)
    for n, text in state["results"].items():
        if text and int(n) in files:
            write_text(profile.results / files[int(n)].name, text)
    data.pop("recheck")
    write_json(profile.dir / FILE, data)
