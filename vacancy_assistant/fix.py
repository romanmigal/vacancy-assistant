"""Правка критериев по одной вакансии: «оценка должна быть выше / ниже».

Шаги окна «Мои оценки» в карточке вакансии: своя оценка и причина (сохраняется в мои-оценки.md, как в калибровке) →
что повлияло на оценку (из разбора) → модель предлагает минимальную правку критериев и сразу проверяет её
на этой вакансии → проверка на уже оценённых вакансиях (не сломали ли остальное) → применить.
Рабочий критерии.txt не меняется до «Применить»; ход правки — в настройка/правка по вакансии.json.

Второй путь — правка своими руками: критерии, резюме, «Дополнительно о себе» прямо в окне → сохранить и
пересчитать эту вакансию (recheck). Прежние тексты и разбор — в настройка/пересчёт по вакансии.json,
«Вернуть как было» (undo) восстанавливает их.
"""
import difflib
from datetime import datetime

from . import analysis, answer, criteria_history, settings, setup
from .errors import AssistantError
from .files import decision_yes, say_decision, numbered_files, parse_answer, read_meta, read_vacancy
from .model import ask_model
from .ratings import read_reference, read_rows
from .textio import read_json, read_text, write_json, write_text
from .tune import TUNE_DIR_NAME, TUNE_META_OPTIONS, criteria_excerpt, evaluate, metrics, parse_proposal, valid_criteria

STATE_FILE = "правка по вакансии.json"
RECHECK_FILE = "пересчёт по вакансии.json"


def state_path(profile):
    (profile.dir / TUNE_DIR_NAME).mkdir(exist_ok=True)
    return profile.dir / TUNE_DIR_NAME / STATE_FILE


def read_state(profile, n):
    """Ход правки для вакансии n — если правка была для неё и критерии с тех пор не меняли."""
    st = read_json(state_path(profile), {})
    return st if st.get("n") == n and st.get("base") == profile.criteria_hash() else None


def factors(text):
    """Что повлияло на оценку — из разбора: отметки критериев, требования, «Могу» и «Хочу», сильные стороны, пробелы."""
    p = answer.parse(text)
    why = lambda key: " ".join(p[key]["why"]) if p[key] else ""
    return {"criteria": p["criteria"], "requirements": p["requirements"], "strengths": p["strengths"],
            "gaps": p["gaps"], "can": why("can"), "want": why("want")}


def propose(profile, n, data, ask=None):
    """Модель предлагает минимальную правку критериев под мнение человека. Возвращает (что меняю, текст)."""
    ask = ask or ask_model
    files = numbered_files(profile.vacancies)
    path = files[n]
    vacancy, info = read_vacancy(path)
    meta = read_meta(profile.results / path.name) or {}
    answer = _answer(profile, path)
    up = data["direction"] == "up"
    marked = "\n".join(f"- {m}" for m in data.get("marks") or []) or "— (не отмечено)"
    tried = ("\n\nУже предлагали — человек попросил другой вариант, не повторяй:\n"
             + "\n".join(f"- {h}" for h in data.get("history") or [])) if data.get("history") else ""
    prompt = f"""Ты настраиваешь критерии отбора вакансий. Модель-оценщик получает эти критерии вместе с резюме
и текстом вакансии и решает, стоит ли откликаться. Человек не согласен с её оценкой одной вакансии:
по его мнению, такие вакансии нужно оценивать {"ВЫШЕ" if up else "НИЖЕ"}. Предложи минимальную правку критериев.

=== ТЕКУЩИЕ КРИТЕРИИ ===
{profile.read_criteria()}

=== ВАКАНСИЯ ===
{info['title']}
{vacancy[:4000]}

=== ОЦЕНКА МОДЕЛИ ===
Оценка: {meta.get('score')}/10, откликаться: {meta.get('decision') or '?'}
{criteria_excerpt(answer)}

=== МНЕНИЕ ЧЕЛОВЕКА ===
Оценка: {data.get('score') or '—'}/10 (Могу {data.get('can') or '—'}, Хочу {data.get('want') or '—'}), откликаться: {data.get('decision') or '—'}
Почему: {data.get('reason') or 'не указано'}
Что модель, по его мнению, учла неверно:
{marked}{tried}

Правила:
- Правка минимальная: измени или ослабь один критерий либо добавь строку в мягкие плюсы или минусы.
  Остальное оставь дословно.
- {"Не отсекай такие вакансии, но и не открывай дорогу явно неподходящим." if up else "Отсекай такие вакансии, но не задевай подходящие."}
- Пиши общее правило, которое можно проверить по тексту любой вакансии. Не упоминай компании,
  названия вакансий и номера.
- Критерии не создают опыт. Если оценку снижает пробел в резюме, можно лишь указать, что отсутствие
  такого опыта при смежном опыте — не причина для отказа.
- Сохрани структуру: блок «Жёсткие (…)» с пунктами К1., К2., … и блок «Мягкие (…)» со строками на «+» и «−».
  Не больше 8 жёстких критериев.

Ответь строго так:
Что меняю: <одно предложение>
=== КРИТЕРИИ ===
<полный новый текст критериев>
=== КОНЕЦ ===
"""
    result = parse_proposal(ask(prompt, settings.MODEL, TUNE_META_OPTIONS))
    if not result:
        raise AssistantError("Модель ответила не по формату — нажмите «ИИ предложит другой вариант».")
    return result


def _answer(profile, path):
    """Текст разбора вакансии."""
    result = profile.results / path.name
    return read_text(result) if result.exists() else ""


def keep_unchanged(current, candidate):
    """Строки, которые модель «поправила» по мелочи (опечатки, «интересна» → «интересны»), — как были:
    правка должна менять смысл одного правила, а не переписывать остальные."""
    old = current.splitlines()
    out = []
    for line in candidate.splitlines():
        best = max(old, key=lambda o: difflib.SequenceMatcher(None, o, line).ratio(), default="")
        close = line != best and line.strip() and difflib.SequenceMatcher(None, best, line).ratio() >= 0.9
        out.append(best if close else line)
    return "\n".join(out)


def check_vacancy(profile, n, criteria, ask=None):
    """Разбор вакансии с новыми критериями — не сохраняя: оценка, «Могу», «Хочу», решение."""
    ask = ask or ask_model
    vacancy, _ = read_vacancy(numbered_files(profile.vacancies)[n])
    prompt = profile.analysis_prompt(profile.read_resume(), vacancy, criteria)
    answer = ask(prompt)
    r = parse_answer(answer)
    if r["score"] is None or decision_yes(r["decision"]) is None:
        answer = ask(prompt)
        r = parse_answer(answer)
    return {**r, "excerpt": criteria_excerpt(answer)}


def suggest(profile, n, data, log, ask=None):
    """Задача «Предложить правку»: правка (или своя — data["manual"]) → проверка → проверка на этой вакансии."""
    files = numbered_files(profile.vacancies)
    if n not in files:
        raise AssistantError(f"Нет вакансии {n}.")
    path = files[n]
    meta = read_meta(profile.results / path.name) or {}
    current = profile.read_criteria()
    if (data.get("manual") or "").strip():
        what, candidate = "ручная правка", data["manual"].strip()
    else:
        log("Модель предлагает правку критериев…")
        what, candidate = propose(profile, n, data, ask)
        candidate = keep_unchanged(current, candidate)
    companies = [{"company": read_vacancy(files[k])[1]["company"]} for k in {n, *read_reference_safe(profile)} if k in files]
    problem = valid_criteria(candidate, companies)
    if not problem and " ".join(candidate.split()) == " ".join(current.split()):
        problem = "критерии не изменились"
    after = None
    if not problem:
        log(f"Что меняю: {what}\nПроверяю на этой вакансии…")
        after = check_vacancy(profile, n, candidate, ask)
        log(f"Было: {meta.get('score')}, {say_decision(meta.get('decision'))} → стало: {after['score']}, {say_decision(after['decision'])}")
    up = data["direction"] == "up"
    achieved = bool(after and after["score"] is not None and meta.get("score") is not None
                    and (after["score"] > meta["score"] if up else after["score"] < meta["score"]))
    state = {"n": n, "base": profile.criteria_hash(), "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
             "direction": data["direction"], "reason": data.get("reason", ""), "marks": data.get("marks") or [],
             "history": (data.get("history") or []) + ([what] if what != "ручная правка" else []),
             "what": what, "criteria": candidate, "problem": problem,
             "diff": list(difflib.unified_diff(current.splitlines(), candidate.splitlines(), lineterm="", n=1))[2:],
             "before": {"score": meta.get("score"), "decision": meta.get("decision", "")},
             "after": after, "achieved": achieved, "reference": None}
    write_json(state_path(profile), state)
    if problem:
        log(f"Правка отброшена: {problem}")
    return state


def read_reference_safe(profile):
    try:
        return read_reference(profile)
    except AssistantError:
        return {}


def check_reference(profile, n, log, ask=None):
    """Задача «Проверить на оценённых»: прогон текущих и новых критериев на ваших оценках, показатели."""
    state = read_state(profile, n)
    if not state or state.get("problem"):
        raise AssistantError("Нет предложенной правки критериев — сначала получите её на шаге «Правка».")
    ref = read_reference_safe(profile)
    if not ref:
        raise AssistantError("Нет оценённых вакансий — проверить не на чем. Оцените вакансии в «Калибровке».")
    out = profile.dir / TUNE_DIR_NAME / "правка"
    log(f"Текущие критерии: прогон {len(ref)} оценённых вакансий…")
    before = evaluate(profile, profile.read_criteria(), ref, out / "было", log, ask)
    log(f"Новые критерии: прогон {len(ref)} оценённых вакансий…")
    after = evaluate(profile, state["criteria"], ref, out / "стало", log, ask)
    was = {r["n"]: r for r in before}
    state["reference"] = {
        "before": metrics(before), "after": metrics(after),
        "changed": [{"n": r["n"], "title": r["title"], "yes": r["yes"], "before": was[r["n"]]["model_yes"],
                     "after": r["model_yes"], "before_score": was[r["n"]]["model_score"], "after_score": r["model_score"]}
                    for r in after if r["n"] in was and r["model_yes"] != was[r["n"]]["model_yes"]]}
    write_json(state_path(profile), state)
    log(f"Было: {state['reference']['before']}\nСтало: {state['reference']['after']}")
    return state


def apply(profile, n):
    """Применяет предложенную правку: новая версия критериев (прежняя — в истории)."""
    state = read_state(profile, n)
    if not state or state.get("problem"):
        raise AssistantError("Правка устарела: критерии поменялись после неё. Предложите правку заново.")
    criteria_history.record(profile, profile.read_criteria(), f"до правки по вакансии {n:02d}")
    m = (state.get("reference") or {}).get("after")
    measure = {"всего": m["всего"], "совпало": m["решение совпало"], "пропущено": m["пропущено подходящих"],
               "лишних": m["лишних да"]} if m else None
    write_text(profile.criteria_file, state["criteria"].rstrip("\n") + "\n")
    criteria_history.record(profile, state["criteria"], f"правка по вакансии {n:02d}: {state['what']}", measure,
                            kind="fix" if measure else "manual")
    state_path(profile).unlink(missing_ok=True)


def recheck_path(profile):
    (profile.dir / TUNE_DIR_NAME).mkdir(exist_ok=True)
    return profile.dir / TUNE_DIR_NAME / RECHECK_FILE


def read_recheck(profile, n):
    st = read_json(recheck_path(profile), {})
    return st if st.get("n") == n else None


def _outcome(text):
    """Оценка из разбора — для «было → стало»: общая, «Могу», «Хочу», решение, отметки критериев, сколько требований с ❌."""
    r = parse_answer(text) if text else {}
    p = answer.parse(text) if text else {"criteria": [], "requirements": []}
    marks = [{"k": c["k"], "mark": c["mark"]} for c in p["criteria"]]
    return {k: r.get(k) for k in ("score", "can", "want", "decision")} | {
        "criteria": marks, "failed": sum(1 for q in p["requirements"] if not q["ok"])}


def recheck(profile, n, data, log, ask=None):
    """Задача «Сохранить и пересчитать»: свои правки критериев, резюме, «о себе» — в профиль, затем новый разбор
    этой вакансии. Прежние тексты и разбор запоминаются, чтобы можно было вернуть как было."""
    files = numbered_files(profile.vacancies)
    if n not in files:
        raise AssistantError(f"Нет вакансии {n}.")
    path = files[n]
    old = setup.answers_from_profile(profile)
    edits = {k: data[k] for k in ("criteria", "resume", "facts") if data.get(k) is not None
             and " ".join(str(data[k]).split()) != " ".join(str(old.get(k) or "").split())}
    if "resume" in edits and not old["resume_editable"]:
        raise AssistantError("Резюме лежит во внешнем файле — поправьте его там или в «Параметры → Резюме».")
    if "criteria" in edits and not edits["criteria"].strip():
        raise AssistantError("Критерии не могут быть пустыми.")
    result = profile.results / path.name
    before = read_text(result) if result.exists() else ""
    if edits:
        log("Сохраняю: " + ", ".join({"criteria": "критерии", "resume": "резюме", "facts": "«о себе»"}[k] for k in edits))
        if "criteria" in edits:
            criteria_history.record(profile, old["criteria"], f"до правки по вакансии {n:02d}")
        setup.update_profile(profile, edits, log=lambda *_: None)
    log("Пересчитываю вакансию…")
    analysis.full_analysis(profile, path, log=log, ask=ask)
    after = read_text(result)
    state = {"n": n, "date": datetime.now().strftime("%Y-%m-%d %H:%M"), "changed": sorted(edits),
             "old": {k: old.get(k) or "" for k in edits}, "result": before,
             "before": _outcome(before), "after": _outcome(after)}
    write_json(recheck_path(profile), state)
    b, a = state["before"], state["after"]
    log(f"Было: {b['score']}, {say_decision(b['decision'])} → стало: {a['score']}, {say_decision(a['decision'])}")
    return state


def undo(profile, n):
    """«Вернуть как было»: прежние критерии, резюме, «о себе» и прежний разбор вакансии."""
    state = read_recheck(profile, n)
    if not state:
        raise AssistantError("Нечего возвращать: пересчёта по этой вакансии не было.")
    if state["old"]:
        setup.update_profile(profile, state["old"], log=lambda *_: None)
    path = numbered_files(profile.vacancies).get(n)
    if path and state["result"]:
        write_text(profile.results / path.name, state["result"])
    recheck_path(profile).unlink(missing_ok=True)


def view(profile, n):
    """Для окна: вакансия, оценка модели, что повлияло, своя оценка, ход правки и сколько оценённых вакансий."""
    files = numbered_files(profile.vacancies)
    if n not in files:
        raise AssistantError(f"Нет вакансии {n}.")
    path = files[n]
    meta = read_meta(profile.results / path.name) or {}
    mine = read_rows(profile).get(n) or {}
    profiled = setup.answers_from_profile(profile)
    return {"n": n, "title": meta.get("title") or read_vacancy(path)[1]["title"], "company": meta.get("company", ""),
            "model": {"score": meta.get("score"), "decision": meta.get("decision", ""), "can": meta.get("can"),
                      "want": meta.get("want"), "stage": meta.get("stage", "")},
            "factors": factors(_answer(profile, path)),
            "mine": {"score": mine.get("score"), "can": mine.get("can"), "want": mine.get("want"),
                     "decision": mine.get("decision", ""), "reason": mine.get("reason", "")},
            "criteria": profile.read_criteria(),
            "resume": profiled["resume"], "facts": profiled["facts"], "resume_editable": profiled["resume_editable"],
            "recheck": read_recheck(profile, n),
            "state": read_state(profile, n), "reference": len(read_reference_safe(profile)),
            "two_stage": profile.two_stage}
