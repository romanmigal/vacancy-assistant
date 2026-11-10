"""Автонастройка критериев — той моделью, что выбрана в профиле (Gemma или GigaChat).

Цикл: эталон (мои-оценки.md) → прогон текущих критериев → модель предлагает правку по расхождениям →
прогон кандидата → оставляем, только если показатели лучше. Рабочий критерии.txt не меняется:
лучшая версия и отчёт — в профили/<имя>/настройка/, применить — tune apply.
"""
import difflib
import re
import shutil
from datetime import date

from . import criteria_history, settings
from .errors import AssistantError
from .files import decision_yes, numbered_files, parse_answer, read_vacancy, say_decision
from .model import ask_model, current_model
from .ratings import read_reference
from .textio import log_print, write_json, write_text

TUNE_DIR_NAME = "настройка"
TUNE_SEED = 42            # одинаковое «зерно» случайности — чтобы сравнивать версии, а не шум
# Проверяем критерии на коротком скоринге: именно он решает, кому делать полный разбор, — и он в 4 раза быстрее
TUNE_OPTIONS = {**settings.SCORING_OPTIONS, "seed": TUNE_SEED}
TUNE_FULL_OPTIONS = {**settings.OPTIONS, "seed": TUNE_SEED}     # разбор в одну ступень — проверяем полным разбором
TUNE_META_OPTIONS = {"temperature": 0.4, "num_predict": 3000, "num_ctx": 16384}


def evaluate(profile, criteria, ref, out_dir, log=None, ask=None):
    """Разбор эталонных вакансий с данными критериями. Ответы — в out_dir, итог — строки для показателей."""
    log, ask = log or log_print, ask or ask_model
    out_dir.mkdir(parents=True, exist_ok=True)
    resume = profile.read_resume()
    files = numbered_files(profile.vacancies)
    rows = []
    for n in sorted(ref):
        if n not in files:
            log(f"  {n:02d}: нет файла вакансии — пропускаю")
            continue
        vacancy, info = read_vacancy(files[n])
        if profile.two_stage:
            answer = ask(profile.scoring_prompt(resume, vacancy, criteria), settings.MODEL, TUNE_OPTIONS)
        else:
            answer = ask(profile.analysis_prompt(resume, vacancy, criteria), settings.MODEL, TUNE_FULL_OPTIONS)
        write_text(out_dir / f"{n:02d}.md", answer + "\n")
        r = parse_answer(answer)
        rows.append({"n": n, "title": info["title"], "company": info["company"], "answer": answer,
                     "model_score": r["score"], "model_yes": decision_yes(r["decision"]), **ref[n]})
        log(f"  {n:02d}: модель {r['score']}, {say_decision(r['decision'])} | я {ref[n]['score']}, {ref[n]['decision']}")
    return rows


def metrics(rows):
    m = {"всего": len(rows),
         "решение совпало": sum(r["model_yes"] == r["yes"] for r in rows),
         "пропущено подходящих": sum(r["yes"] and r["model_yes"] is False for r in rows),
         "лишних да": sum((not r["yes"]) and r["model_yes"] is True for r in rows)}
    diffs = [abs(r["model_score"] - r["score"]) for r in rows
             if r["model_score"] is not None and r["score"] is not None]
    m["оценка ±2"] = sum(d <= 2 for d in diffs)
    m["среднее расхождение"] = round(sum(diffs) / len(diffs), 2) if diffs else None
    return m


def better(a, b):
    """Лучше ли показатели a, чем b: меньше пропущенных подходящих → больше совпавших решений →
    больше оценок в пределах ±2 → меньше среднее расхождение."""
    key = lambda m: (-m["пропущено подходящих"], m["решение совпало"], m["оценка ±2"],
                     -(m["среднее расхождение"] or 0))
    return key(a) > key(b)


def criteria_excerpt(answer):
    """Из разбора — блок «Критерии» и строки «Хочу» и «Откликаться»: этого хватает, чтобы понять ошибку."""
    keep, inside = [], False
    for l in answer.splitlines():
        s = l.strip().strip("*")
        if s.startswith("Критерии"):
            inside = True
            continue
        if inside and (not s or s.startswith("Требования")):
            inside = False
        if inside or s.startswith(("Хочу", "Откликаться")):
            keep.append(l.strip())
    return "\n".join(keep)


def propose(criteria, rows, history, ask=None):
    """Просит модель переписать критерии под расхождения. Возвращает (что меняю, новый текст) или None."""
    ask = ask or ask_model
    wrong = [r for r in rows if r["model_yes"] != r["yes"]]
    right = [r for r in rows if r["model_yes"] == r["yes"]]
    wrong.sort(key=lambda r: not r["yes"])           # сначала пропущенные подходящие — самая дорогая ошибка
    cases = "\n\n".join(
        f"Вакансия: {r['title']}\n"
        f"Человек: {'ДА — хочет откликнуться' if r['yes'] else 'НЕТ — не хочет'}. Причина: {r['reason'] or 'не указана'}\n"
        f"Модель решила: {'да' if r['model_yes'] else 'нет'}. Её проверка критериев:\n{criteria_excerpt(r['answer'])}"
        for r in wrong)
    keep = "\n".join(f"- {r['title']}: {'да' if r['yes'] else 'нет'} ({r['reason'] or '—'})" for r in right)
    tried = ("\n\nУже пробовали и это НЕ помогло — не повторяй:\n" + "\n".join(f"- {h}" for h in history)) if history else ""
    prompt = f"""Ты настраиваешь критерии отбора вакансий. Модель-оценщик получает эти критерии вместе с резюме
и текстом вакансии и решает, стоит ли откликаться. Ниже текущие критерии и вакансии, где модель
ошиблась: её решение не совпало с решением человека. Перепиши критерии, чтобы исправить ошибки.

=== ТЕКУЩИЕ КРИТЕРИИ ===
{criteria}

=== ОШИБКИ МОДЕЛИ ===
{cases}

=== ЗДЕСЬ МОДЕЛЬ ПРАВА — НЕ СЛОМАЙ ===
{keep or '—'}{tried}

Правила:
- Сохрани структуру: блок «Жёсткие (…)» с пунктами К1., К2., … и блок «Мягкие (…)» со строками на «+» и «−».
- Главное — не отсекать то, что человек хочет. Потом — отсекать то, что он не хочет.
- Опирайся только на причины, которые назвал человек. Не придумывай новых требований.
- Пиши общие правила, которые можно проверить по тексту любой вакансии. Не упоминай конкретные
  компании, названия вакансий и номера.
- Меняй только то, что нужно для этих ошибок; остальное оставь дословно.
- Не больше 8 жёстких критериев.

Ответь строго так:
Что меняю: <одно предложение>
=== КРИТЕРИИ ===
<полный новый текст критериев>
=== КОНЕЦ ===
"""
    return parse_proposal(ask(prompt, settings.MODEL, TUNE_META_OPTIONS))


def parse_proposal(answer):
    """Ответ «Что меняю: … === КРИТЕРИИ === … === КОНЕЦ ===» → (что меняю, новый текст) или None."""
    m = re.search(r"=== КРИТЕРИИ ===\s*\n(.*?)\n\s*=== КОНЕЦ ===", answer, re.S)
    what = re.search(r"Что меняю:\s*(.+)", answer)
    if not m:
        return None
    return (what.group(1).strip() if what else "—"), m.group(1).strip()


def valid_criteria(text, rows):
    """Проверка кандидата: структура на месте и нет названий компаний из эталона (защита от подгонки)."""
    nums = re.findall(r"^К(\d+)\.", text, re.M)
    if not nums or nums != [str(i) for i in range(1, len(nums) + 1)] or len(nums) > 8:
        return "нарушена нумерация К1., К2., … или больше 8 жёстких критериев"
    if "Жёсткие" not in text:
        return "нет блока «Жёсткие»"
    for r in rows:
        company = r["company"].strip()
        if len(company) > 3 and company.lower() in text.lower() and company != "Анонимный работодатель":
            return f"упомянута компания из эталона: {company}"
    return None


def tune(profile, rounds=3, log=None, ask=None, only=None):
    """Автонастройка. only — номера вакансий для эталона (выбранные в окне калибровки), иначе все оценённые.
    Возвращает лучшую версию: {version, criteria, metrics, rows}."""
    log, ask = log or log_print, ask or ask_model
    ref = read_reference(profile)
    if only is not None:
        ref = {n: v for n, v in ref.items() if n in set(only)}
    if len(ref) < 6:
        raise AssistantError(f"Оценённых вакансий для настройки: {len(ref)}. Нужно хотя бы 6, лучше 10–15.")
    tune_dir = profile.dir / TUNE_DIR_NAME
    tune_dir.mkdir(exist_ok=True)
    report = [f"# Автонастройка критериев — {date.today().strftime('%d.%m.%Y')}", "",
              f"Профиль: {profile.display_name}. Эталон: {len(ref)} вакансий из мои-оценки.md. "
              f"Модель: {current_model()}, seed {TUNE_SEED}.", ""]

    criteria = profile.read_criteria()
    log(f"Версия 0 — текущие критерии: прогон {len(ref)} вакансий…")
    rows = evaluate(profile, criteria, ref, tune_dir / "v0", log, ask)
    first = rows
    best = {"version": 0, "criteria": criteria, "metrics": metrics(rows), "rows": rows}
    write_text(tune_dir / "критерии v0.txt", criteria + "\n")
    table = [("v0", "текущие критерии", best["metrics"], "исходная")]
    log(f"Показатели v0: {best['metrics']}")

    best = _rounds(profile, ref, tune_dir, best, rounds, table, log, ask)

    write_text(tune_dir / "критерии — лучшие.txt", best["criteria"] + "\n")
    rest = [r for r in best["rows"] if r["model_yes"] != r["yes"]]
    write_text(tune_dir / "отчёт.md", "\n".join(report + _report(profile, criteria, best, table, rest)) + "\n")
    write_json(tune_dir / "итог.json", _summary(ref, criteria, first, best, table, rest))   # итог для окна
    criteria_history.import_tune(profile, tune_dir)          # все проверенные версии — в историю критериев
    log(f"\nГотово. Лучшая версия: v{best['version']} {best['metrics']}\nОтчёт: {tune_dir / 'отчёт.md'}")
    return best


def _rounds(profile, ref, tune_dir, best, rounds, table, log, ask):
    """Раунды правки: модель предлагает новые критерии, кандидат прогоняется на эталоне и принимается, если лучше.
    Каждая версия — строкой в table. Возвращает лучшую версию."""
    history = []
    for k in range(1, rounds + 1):
        if best["metrics"]["решение совпало"] == best["metrics"]["всего"]:
            log("Все решения совпали — настраивать нечего.")
            break
        log(f"\nРаунд {k}: {current_model()} предлагает правку…")
        proposal = propose(best["criteria"], best["rows"], history, ask)
        if not proposal:
            log(f"  {current_model()} ответила не по формату — раунд пропущен.")
            table.append((f"v{k}", "ответ не по формату", None, "отброшена"))
            continue
        what, candidate = proposal
        problem = valid_criteria(candidate, best["rows"])
        write_text(tune_dir / f"критерии v{k}.txt", candidate + "\n")
        if problem:
            log(f"  Отброшено: {problem}")
            history.append(f"{what} (отброшено: {problem})")
            table.append((f"v{k}", what, None, f"отброшена: {problem}"))
            continue
        log(f"  Что меняю: {what}\n  Прогон кандидата…")
        rows_k = evaluate(profile, candidate, ref, tune_dir / f"v{k}", log, ask)
        m_k = metrics(rows_k)
        log(f"  Показатели v{k}: {m_k}")
        if better(m_k, best["metrics"]):
            best = {"version": k, "criteria": candidate, "metrics": m_k, "rows": rows_k}
            table.append((f"v{k}", what, m_k, "**принята**"))
        else:
            history.append(what)
            table.append((f"v{k}", what, m_k, "отброшена: не лучше"))
    return best


def _report(profile, criteria, best, table, rest):
    """Строки отчёта после шапки: таблица версий, что изменится и как применить, оставшиеся расхождения."""
    report = ["| Версия | Что изменено | Решение совпало | Пропущено подходящих | Лишних «да» | Оценка ±2 | Ср. расхождение | Итог |",
              "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for v, what, m, verdict in table:
        if m:
            report.append(f"| {v} | {what} | {m['решение совпало']} из {m['всего']} | {m['пропущено подходящих']} | "
                          f"{m['лишних да']} | {m['оценка ±2']} | {m['среднее расхождение']} | {verdict} |")
        else:
            report.append(f"| {v} | {what} | — | — | — | — | — | {verdict} |")
    report += ["", f"**Лучшая версия: v{best['version']}** → `{TUNE_DIR_NAME}/критерии — лучшие.txt`.", ""]
    if best["version"]:
        diff = difflib.unified_diff(criteria.splitlines(), best["criteria"].splitlines(),
                                    "критерии.txt (сейчас)", f"v{best['version']}", lineterm="")
        report += ["## Что изменится", "", "```diff", *diff, "```", "",
                   "## Как применить", "", "Прочитайте изменения: формулировки должны быть вашими. Затем:", "",
                   "```bash", f"python3 razbor.py --profile {profile.name} tune apply", "```", "",
                   "> Эталон небольшой: модель могла подогнать критерии под эти вакансии. "
                   "Проверьте результат на 3–5 новых вакансиях."]
    else:
        report += ["Улучшить не удалось — текущие критерии остаются. Если ошибки остались, их причины, "
                   "вероятно, не записаны в колонке «Почему» — допишите их и запустите настройку снова."]
    if rest:
        report += ["", "## Оставшиеся расхождения", ""] + [
            f"- {r['n']:02d}. {r['title']}: я — {'да' if r['yes'] else 'нет'}, модель — {'да' if r['model_yes'] else 'нет'}"
            for r in rest]
    return report


def _summary(ref, criteria, first, best, table, rest):
    """Итог для окна программы: версии с показателями и что изменится."""
    return {"date": date.today().isoformat(), "best": best["version"], "reference": len(ref),
            "versions": [{"version": v, "what": what, "metrics": m, "verdict": verdict.strip("*")}
                         for v, what, m, verdict in table],
            "diff": list(difflib.unified_diff(criteria.splitlines(), best["criteria"].splitlines(), lineterm="", n=1))[2:],
            "rest": [{"n": r["n"], "title": r["title"], "yes": r["yes"], "model_yes": r["model_yes"]} for r in rest],
            # По каждой вакансии: ваша оценка, оценка модели с текущими критериями (было) и с лучшими (стало)
            "rows": [{"n": a["n"], "title": a["title"], "company": a["company"], "score": a["score"], "yes": a["yes"],
                      "before": {"score": a["model_score"], "yes": a["model_yes"]},
                      "after": {"score": b["model_score"], "yes": b["model_yes"]}}
                     for a, b in zip(first, best["rows"])]}


def tune_apply(profile, log=None):
    """Применяет лучшую версию критериев; прежние сохраняются в настройка/. Возвращает путь копии."""
    log = log or log_print
    best = profile.dir / TUNE_DIR_NAME / "критерии — лучшие.txt"
    if not best.exists():
        raise AssistantError("Нет результата настройки. Сначала: python3 razbor.py tune")
    criteria_history.record(profile, profile.read_criteria(), "до применения автонастройки")
    backup = profile.dir / TUNE_DIR_NAME / f"критерии до применения {date.today().strftime('%d.%m.%Y')}.txt"
    shutil.copy(profile.criteria_file, backup)
    shutil.copy(best, profile.criteria_file)
    log(f"Применено. Прежние критерии сохранены: {backup.name}\n"
        f"Чтобы пересчитать все разборы по новым критериям: python3 razbor.py --profile {profile.name} --all")
    return backup
