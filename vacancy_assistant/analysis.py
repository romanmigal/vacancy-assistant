"""Разбор вакансий моделью и сопроводительные письма."""
import json
import os
import re
import shutil
import time
from datetime import date, datetime

from . import settings
from .hh import ARCHIVED_FIELD, phase
from .files import decision_yes, say_decision, frontmatter, md_path, parse_answer, read_meta, read_vacancy, requirements, strengths
from .errors import AssistantError
from . import actual, artifacts, cloud, fact_check, funnel, letter_frame, letter_samples, letter_templates
from .model import ask_local, ask_model, current_model
from .summary import write_summary
from .textio import log_print, read_text, write_text


NO_MODEL = "none"           # «стадия» разбора вакансии, сохранённой в режиме «Без модели»
NO_MODEL_TEXT = ("Вакансия сохранена без разбора: в профиле выбран режим «Без модели». Этап, комментарий "
                 "и референсер работают как обычно. Когда включите модель («Параметры → Настройки»), "
                 "программа предложит разобрать такие вакансии.")


def unanalyzed(path):
    """Файла разбора нет или он «пустой» — вакансию сохранили без модели: её нужно разобрать."""
    return not path.exists() or (read_meta(path) or {}).get("stage") == NO_MODEL


def save_unanalyzed(profile, path):
    """Режим «Без модели»: «пустой разбор» — паспорт без оценки. В его свойствах живут этап, комментарий,
    референсер и актуальность, как у разобранной; когда модель включат, вакансию разберут как новую.
    Настоящий разбор не трогаем."""
    target = profile.results / path.name
    if target.exists():
        return target
    profile.results.mkdir(exist_ok=True)
    info = read_vacancy(path)[1]
    meta = {**info, "score": None, "can": None, "want": None, "decision": "", "seconds": 0, "stage": NO_MODEL,
            "date": date.today().isoformat()}
    return save_result(profile, path, info, NO_MODEL_TEXT, meta, record=False)


def save_result(profile, path, info, answer, meta, record=True):
    """Файл разбора: «паспорт» (из него строится сводка), заголовок, ссылки и ответ модели.
    record — записать итог в историю разборов (у «пустого разбора» без модели — нет)."""
    target = profile.results / path.name
    write_text(target,
               frontmatter(target) +                       # заметка из прошлого разбора сохраняется
               f"<!-- {json.dumps(meta, ensure_ascii=False)} -->\n"
               f"# {info['title']} — {info['company']}\n\n"
               f"[Вакансия](../vacancies/{md_path(path.name)}) · {info['link']}\n\n"
               f"{answer}\n")
    if record:
        funnel.record_analysis(profile, target, meta, profile.input_hashes())
    # Вакансию скачали уже закрытой (hh: «в архиве») — сразу отмечаем это, как проверка актуальности
    if f"**{ARCHIVED_FIELD}:** вакансия в архиве" in read_text(path) and not actual.read(target)["checked"]:
        actual.record(target, actual.GONE)
    return target


def full_analysis(profile, path, resume=None, log=None, ask=None, local=None):
    """Полный разбор одной вакансии: требования, сильные стороны, пробелы. Возвращает (файл, итог, секунды).
    Ответ не по формату — ещё одна попытка; облачная модель снова не ответила (GigaChat отказывается говорить
    на «чувствительные» темы — например, вакансия в Донецке) — разбирает локальная модель (local), если она есть."""
    log, ask = log or log_print, ask or ask_model
    resume = resume if resume is not None else profile.read_resume()
    vacancy, info = read_vacancy(path)
    prompt = profile.analysis_prompt(resume, vacancy)
    start, used = time.time(), current_model()
    answer = ask(prompt)
    result = parse_answer(answer)
    if not answered(result):
        log("      Модель ответила не по формату — спрашиваю ещё раз…")
        answer = ask(prompt)
        result = parse_answer(answer)
    if not answered(result) and cloud.active(profile):
        log(f"      {used} не стал разбирать вакансию — разбираю локальной моделью {settings.MODEL}…")
        try:
            answer = (local or ask_local)(prompt)
            result, used = parse_answer(answer), settings.MODEL
        except AssistantError as e:
            log(f"      Локальная модель недоступна: {e}")
    seconds = round(time.time() - start)
    if not answered(result):
        # Модель так и не ответила по формату — прежний разбор (если он есть) не трогаем
        raise AssistantError("Полный разбор не получился: модель ответила не по формату — "
                             + ("оставлена прежняя оценка" if (profile.results / path.name).exists()
                                else "вакансия пока без оценки, её можно разобрать кнопкой «Разобрать заново»")
                             + ". Ответ модели: " + " ".join(answer.split())[:200])
    meta = {**info, **result, "stage": "full", "seconds": seconds, "model": used,
            "prompt": settings.ANALYSIS_TEMPLATE.name, "criteria_hash": profile.criteria_hash(), "resume_hash": profile.resume_hash(),
            "date": date.today().isoformat()}
    return save_result(profile, path, info, answer, meta), result, seconds


def answered(result):
    """Ответ модели разобрался: есть оценка и решение."""
    return result["score"] is not None and decision_yes(result["decision"]) is not None


def analyze(profile, redo=False, log=None, ask=None, summary=True, only=None):
    """Разбор новых вакансий (redo — всех; only — только этих, заново). В две ступени (по умолчанию):
    короткий скоринг всех, полный разбор — только для «да» и «да, но…»; в одну (profile.two_stage = False) —
    сразу полный разбор каждой. Пересобирает сводку. Возвращает файлы разборов."""
    log, ask = log or log_print, ask or ask_model
    profile.results.mkdir(exist_ok=True)
    files = sorted(profile.vacancies.glob("*.md"))
    if only is not None:
        todo, redo = [f for f in files if f.name in set(only)], True
    else:
        todo = [f for f in files if redo or unanalyzed(profile.results / f.name)]
    if profile.no_model:                       # «Без модели»: только сохранить, без оценки
        if todo:
            log(f"Модель не используется — сохранено без разбора: {len(todo)}")
        done = [save_unanalyzed(profile, f) for f in todo]
        if summary:
            write_summary(profile, log)
        return done
    resume = profile.read_resume()
    phase(log, f"Оцениваю вакансии моделью {current_model()}")
    log(f"Всего в списке: {len(files)}, " + (f"оценить заново: {len(todo)}" if redo else f"новых: {len(todo)}")
        + ((". Сначала короткая оценка (~15 с), для «да» и «возможно» — полный разбор (~1 мин)" if profile.two_stage
            else ". Каждую — полным разбором" + (" (облачная модель — секунды на вакансию)" if cloud.active(profile)
                                                  else " (~1 мин)")) if todo else ""))

    done, full = [], 0
    for i, path in enumerate(todo, 1):
        vacancy, info = read_vacancy(path)
        log(f"[{i}/{len(todo)}] Оцениваю: {info['title']} — {info['company']}")
        if not profile.two_stage:                                  # одна ступень — сразу полный разбор
            try:
                target, result, full_sec = full_analysis(profile, path, resume, log, ask)
                full += 1
                log(f"      оценка {result['score']}/10, откликаться: {say_decision(result['decision'])} ({full_sec} с)")
                done.append(target)
            except AssistantError as e:
                if type(e).__name__ == "Stopped":
                    raise
                log(f"      {e}")
            continue
        start = time.time()
        answer = ask(profile.scoring_prompt(resume, vacancy), settings.MODEL, settings.SCORING_OPTIONS)
        seconds = round(time.time() - start)
        result = parse_answer(answer)
        # Короткую оценку сохраняем сразу: если разбор остановят на полном разборе, она не пропадёт
        meta = {**info, **result, "stage": "short", "seconds": seconds, "model": current_model(),
                "prompt": settings.ANALYSIS_TEMPLATE.name, "scoring": settings.SCORING_TEMPLATE.name,
                "criteria_hash": profile.criteria_hash(), "resume_hash": profile.resume_hash(),
                "date": date.today().isoformat()}
        target = save_result(profile, path, info, answer, meta)
        if decision_yes(result["decision"]):
            log(f"      короткая оценка {result['score']}/10, {say_decision(result['decision'])} ({seconds} с) — делаю полный разбор…")
            try:
                target, result, full_sec = full_analysis(profile, path, resume, log, ask)
                full += 1
                log(f"      оценка {result['score']}/10, откликаться: {say_decision(result['decision'])} ({full_sec} с)")
            except AssistantError as e:
                if type(e).__name__ == "Stopped":                  # «Остановить» — не ошибка разбора
                    raise
                log(f"      {e}")
        else:
            log(f"      оценка {result['score']}/10, откликаться: {say_decision(result['decision'])} ({seconds} с)")
        done.append(target)
    if todo and profile.two_stage:
        log(f"Полный разбор сделан для {full} из {len(todo)}.")

    if summary:
        write_summary(profile, log)
    return done


HISTORY = "история"          # прежние версии писем: письма/история/<вакансия>/<дата время>.md


def letter_history(profile, name):
    """Прежние версии письма вакансии, новые сверху: [файл]."""
    folder = profile.letters / HISTORY / name[:-3]
    return sorted(folder.glob("*.md"), reverse=True) if folder.exists() else []


def archive_letter(profile, target, root=None):
    """Откладывает текущее письмо в историю, чтобы новая версия его не затёрла (root — папка писем этого вида)."""
    if not target.exists():
        return None
    folder = (root or profile.letters) / HISTORY / target.stem
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.fromtimestamp(target.stat().st_mtime).strftime("%Y-%m-%d %H-%M-%S")
    dest, i = folder / f"{stamp}.md", 1
    while dest.exists():                       # две версии в одну секунду
        dest, i = folder / f"{stamp}-{i}.md", i + 1
    shutil.move(str(target), str(dest))
    return dest


def write_letter(profile, path, resume=None, log=None, ask=None, example=None, template=None):
    """Письмо для одной разобранной вакансии (path — файл разбора), без проверки оценки. template — id шаблона
    (нет — по умолчанию), example — его текст, поправленный для этого письма.
    Если письмо уже было — оно уходит в историю. Возвращает файл письма."""
    log, ask = log or log_print, ask or ask_model
    tpl = letter_templates.get(profile, template)
    resume = resume if resume is not None else profile.read_resume()
    profile.letters.mkdir(exist_ok=True)
    meta = read_meta(path)
    vacancy, _ = read_vacancy(profile.vacancies / path.name)
    greeting, middle = letter_frame.split_example(example or tpl["text"], profile)   # модели — образец без рамки
    samples = letter_samples.pick(profile, path.name, meta["title"])                # свои отправленные — образцы стиля
    text = read_text(path)
    earlier = letter_samples.earlier(profile, path.name, meta["company"])          # уже отправленное в эту компанию
    prompt = profile.letter_prompt(resume, vacancy, strengths(text), middle, samples=samples,
                                   requirements=requirements(text), earlier=earlier)
    start = time.time()
    letter = ask(prompt, settings.LETTER_MODEL, settings.LETTER_OPTIONS)
    seconds = round(time.time() - start)
    letter = letter_frame.assemble(profile, greeting, letter_frame.strip_frame(letter, profile))
    info = {"model": current_model(), "prompt": settings.LETTER_TEMPLATE.name, "template": tpl["name"],
            "samples": len(samples), "date": date.today().isoformat(), "chars": len(letter), "seconds": seconds}
    target = profile.letters / path.name
    archive_letter(profile, target)
    write_text(target,
               f"<!-- {json.dumps(info, ensure_ascii=False)} -->\n"
               f"# Письмо: {meta['title']} — {meta['company']}\n\n"
               f"[Вакансия]({meta['link']}) · [Разбор](../разборы/{md_path(path.name)})\n\n"
               f"---\n\n{letter}\n")
    log(f"      готово: {len(letter)} знаков ({seconds} с)")
    return target


def resume_fit_history(profile, name):
    """Прежние версии «Резюме под вакансию», новые сверху: [файл]."""
    folder = profile.resume_fits / HISTORY / name[:-3]
    return sorted(folder.glob("*.md"), reverse=True) if folder.exists() else []


NOTHING_TO_DROP = "- нет — весь опыт в резюме работает на эту вакансию"


def without_repeats(text):
    """«Можно не включать» без того, что модель сама же советует включить: пункт, где названо то же
    («Помощник по вакансиям», ACI Worldwide), что есть в «Включить», — противоречие, убираем. Модели
    (особенно GigaChat) нарушают это правило промпта. Названо то же: любое название в кавычках «…» или все
    названия пункта (латиницей, с заглавной) есть во «Включить» — по началу слова, как в сверке с резюме."""
    parts = re.split(r"(?m)^(## .+)$", text)
    heads = [h.strip().lower() for h in parts[1::2]]
    if "## включить в резюме под вакансию" not in heads or "## можно не включать" not in heads:
        return text
    include = parts[2 + 2 * heads.index("## включить в резюме под вакансию")]
    src, i = fact_check.Source(include), 2 + 2 * heads.index("## можно не включать")
    kept, dropped = [], False
    for line in parts[i].splitlines():
        item = line.strip()
        if item.startswith("- ") and " — " in item:
            found = [n for _, n in fact_check.names(item[2:].split(" — ", 1)[0])]
            quoted = [n for n in found if n.startswith("«")]
            if any(src.has_name(n) for n in quoted) or (found and all(src.has_name(n) for n in found)):
                dropped = True
                continue
        kept.append(line)
    if dropped and not any(l.strip().startswith("- ") for l in kept):
        kept.insert(1 if kept and not kept[0].strip() else 0, NOTHING_TO_DROP)
    parts[i] = "\n".join(kept) + ("\n" if parts[i].endswith("\n") else "")
    return "".join(parts)


def write_resume_fit(profile, path, log=None, ask=None):
    """Как подогнать резюме под разобранную вакансию (path — файл разбора): что из резюме и «Дополнительно
    о себе» включить, что можно не включать, «Обо мне» языком вакансии, какие навыки выделить и каких слов вакансии в резюме нет. Только советы
    для копирования — резюме профиля и на hh не меняется. Прежняя версия уходит в историю. Возвращает файл."""
    log, ask = log or log_print, ask or ask_model
    meta = read_meta(path)
    vacancy, _ = read_vacancy(profile.vacancies / path.name)
    prompt = profile.resume_fit_prompt(profile.read_resume(), vacancy, strengths(read_text(path)))
    start = time.time()
    text = without_repeats(ask(prompt, settings.MODEL, settings.RESUME_FIT_OPTIONS).strip())
    seconds = round(time.time() - start)
    info = {"model": current_model(), "prompt": settings.RESUME_FIT_TEMPLATE.name,
            "date": date.today().isoformat(), "chars": len(text), "seconds": seconds}
    profile.resume_fits.mkdir(exist_ok=True)
    target = profile.resume_fits / path.name
    archive_letter(profile, target, profile.resume_fits)
    write_text(target,
               f"<!-- {json.dumps(info, ensure_ascii=False)} -->\n"
               f"# Резюме под вакансию: {meta['title']} — {meta['company']}\n\n"
               f"[Вакансия]({meta['link']}) · [Разбор](../разборы/{md_path(path.name)})\n\n"
               f"---\n\n{text}\n")
    log(f"      готово: {len(text)} знаков ({seconds} с)")
    return target


# Свой текст вместо версии модели: правка показанной версии или письмо, написанное самим
TEXT_KINDS = {"cover": ("letters", "Письмо", "../"),                 # вид → папка профиля, заголовок, путь до профиля
              "referrer": ("referrer_letters", "Референсеру", "../../"),
              "resume": ("resume_fits", "Резюме под вакансию", "../")}
SOURCES = ("edit", "own")                          # правка версии · своё письмо; у версий модели source нет


def save_text(profile, path, kind, text, source, to=""):
    """Сохраняет текст человека новой версией (path — файл разбора): прежняя уходит в историю, как при
    «Написать заново». source — edit (правка) или own (своё); to — кому, для письма референсеру. Возвращает файл."""
    if kind not in TEXT_KINDS or source not in SOURCES:
        raise AssistantError("Неизвестный вид текста.")
    text = "\n".join(line.rstrip() for line in (text or "").strip().splitlines())
    if not text:
        raise AssistantError("Текст пустой — нечего сохранять.")
    folder_attr, head, up = TEXT_KINDS[kind]
    folder = getattr(profile, folder_attr)
    folder.mkdir(parents=True, exist_ok=True)
    target, meta = folder / path.name, read_meta(path)
    old = (read_meta(target) if target.exists() else None) or {}
    info = {"source": source, "date": date.today().isoformat(), "chars": len(text)}
    if kind == "referrer":                         # кому и каким каналом — от прежней версии, если не сказано иначе
        info.update({k: old[k] for k in ("channel", "goal") if old.get(k)}, to=to or old.get("to", ""))
    archive_letter(profile, target, folder)
    title = f"{head}: {info['to']} — {meta['title']}, {meta['company']}" if kind == "referrer" and info["to"] \
        else f"{head}: {meta['title']} — {meta['company']}"
    write_text(target,
               f"<!-- {json.dumps(info, ensure_ascii=False)} -->\n"
               f"# {title}\n\n"
               f"[Вакансия]({meta['link']}) · [Разбор]({up}разборы/{md_path(path.name)})\n\n"
               f"---\n\n{text}\n")
    return target


def text_file(profile, path, kind, key=""):
    """Файл версии письма или резюме под вакансию: key "" — текущая, иначе имя файла в истории (без .md)."""
    folder = getattr(profile, TEXT_KINDS[kind][0])
    f = folder / path.name if not key else folder / HISTORY / path.stem / f"{key}.md"
    if "/" in key or "\\" in key or not f.exists():
        raise AssistantError("Такой версии нет — обновите окно.")
    return f


def mark_sent(profile, path, kind, key="", when=None, trash=None):
    """Отметка «Отправлено» у версии письма или резюме под вакансию: when — дата ("2026-10-28"),
    None — снять отметку. Пишется в паспорт файла; время изменения файла не трогаем — по нему версия стоит
    в списке. Отправленный текст копируется в «Артефакты» вакансии, при снятии отметки копия — в Корзину."""
    if kind not in TEXT_KINDS:
        raise AssistantError("Отправленным можно отметить только письмо или резюме.")
    f = text_file(profile, path, kind, key)
    st, text = f.stat(), read_text(f)
    m = re.match(r"<!-- (\{.*\}) -->\n", text)
    info = json.loads(m.group(1)) if m else {}
    info.pop("sent", None), info.pop("sent_time", None)
    aid = info.pop("artifact", None)
    known = aid and any(e["id"] == aid for e in artifacts.listing(profile, path))
    if when:
        info["sent"] = date.fromisoformat(when).isoformat()
        if info["sent"] == date.today().isoformat():          # отметили в тот же день — время для «Истории»
            info["sent_time"] = datetime.now().strftime("%H:%M:%S")
        if known:                                              # поправили дату — та же копия в артефактах
            artifacts.set_date(profile, path, aid, info["sent"])
        else:
            title = artifacts.TYPES[kind] + (f": {info['to']}" if info.get("to") else "")
            aid = artifacts.add_text(profile, path, kind, title, (text[m.end():] if m else text).split("\n---\n", 1)[-1],
                                     info["sent"])["id"]
        info["artifact"] = aid
    elif known:
        artifacts.remove(profile, path, aid, trash or _trash())
    write_text(f, f"<!-- {json.dumps(info, ensure_ascii=False)} -->\n" + (text[m.end():] if m else text))
    os.utime(f, (st.st_atime, st.st_mtime))
    return info.get("sent", "")


def unmark_artifact(profile, path, aid):
    """Артефакт отправленной версии убрали во вкладке «Артефакты» — снимаем отметку «Отправлено» и с версии."""
    for kind, (attr, _, _) in TEXT_KINDS.items():
        folder = getattr(profile, attr)
        for f in [folder / path.name, *sorted((folder / HISTORY / path.stem).glob("*.md"))]:
            if f.exists() and (read_meta(f) or {}).get("artifact") == aid:
                st, text = f.stat(), read_text(f)
                m = re.match(r"<!-- (\{.*\}) -->\n", text)
                info = {k: v for k, v in json.loads(m.group(1)).items() if k not in ("sent", "sent_time", "artifact")}
                write_text(f, f"<!-- {json.dumps(info, ensure_ascii=False)} -->\n" + text[m.end():])
                os.utime(f, (st.st_atime, st.st_mtime))


def _trash():
    from .backup import move_to_trash
    return move_to_trash


REFERRER_LIMITS = {"invite": 300}               # канал → сколько знаков пропускает
SHORTEN_PROMPT = """Сократи сообщение до {limit} знаков вместе с пробелами — это жёсткий предел. Оставь обращение,
одну фразу о вакансии, один факт из опыта и просьбу; подпись можно убрать. Не добавляй ничего нового.
Ответь только текстом сообщения.

{text}"""


def referrer_history(profile, name):
    """Прежние версии сообщения референсеру, новые сверху: [файл]."""
    folder = profile.referrer_letters / HISTORY / name[:-3]
    return sorted(folder.glob("*.md"), reverse=True) if folder.exists() else []


def write_referrer_letter(profile, path, to, about="", channel="telegram", goal="pass", extra="", log=None, ask=None):
    """Сообщение референсеру для разобранной вакансии (path — файл разбора): кому (to), что о нём известно
    (about), канал и цель. Прежнее сообщение уходит в историю. Возвращает файл."""
    log, ask = log or log_print, ask or ask_model
    meta = read_meta(path)
    vacancy, _ = read_vacancy(profile.vacancies / path.name)
    prompt = profile.referrer_prompt(profile.read_resume(), vacancy, strengths(read_text(path)), meta["title"],
                                     to, about, channel, goal, extra)
    start = time.time()
    text = ask(prompt, settings.LETTER_MODEL, settings.LETTER_OPTIONS)
    limit = REFERRER_LIMITS.get(channel)
    if limit and len(text) > limit:                    # запрос в контакты LinkedIn длиннее не пропустит — сокращаем
        log(f"      {len(text)} знаков — больше {limit}, сокращаю")
        text = ask(SHORTEN_PROMPT.format(limit=limit, text=text), settings.LETTER_MODEL, settings.LETTER_OPTIONS)
    seconds = round(time.time() - start)
    info = {"model": current_model(), "prompt": settings.REFERRER_TEMPLATE.name, "to": to, "channel": channel,
            "goal": goal, "date": date.today().isoformat(), "chars": len(text), "seconds": seconds}
    profile.referrer_letters.mkdir(parents=True, exist_ok=True)
    target = profile.referrer_letters / path.name
    archive_letter(profile, target, profile.referrer_letters)
    write_text(target,
               f"<!-- {json.dumps(info, ensure_ascii=False)} -->\n"
               f"# Референсеру: {to} — {meta['title']}, {meta['company']}\n\n"
               f"[Вакансия]({meta['link']}) · [Разбор](../../разборы/{md_path(path.name)})\n\n"
               f"---\n\n{text}\n")
    log(f"      готово: {len(text)} знаков ({seconds} с)")
    return target


QUESTIONS_HEAD = "## Мои вопросы работодателю"


def interview_prompt(profile, path, template=None):
    vacancy, _ = read_vacancy(profile.vacancies / path.name)
    analysis_text = re.sub(r"\A---\n.*?\n---\n|^<!-- .* -->\n", "", read_text(path), flags=re.S | re.M)
    return profile.interview_prompt(profile.read_resume(), vacancy, analysis_text.strip(), template)


def questions_part(text):
    """Раздел «Мои вопросы работодателю» из ответа модели или файла подготовки: (начало, конец) или None."""
    m = re.search(rf"^#+\s*{QUESTIONS_HEAD.lstrip('# ')}.*?(?=^## |\Z)", text, re.M | re.S)
    return (m.start(), m.end()) if m else None


def write_interview(profile, path, log=None, ask=None):
    """Подготовка к собеседованию для разобранной вакансии (path — файл разбора): истории STAR из резюме
    под главные требования, как отвечать о пробелах и вопросы работодателю. Прежние истории заменяются;
    если вопросы уже есть — они остаются (их заменяет write_questions), а модель пишет только истории.
    Возвращает файл."""
    log, ask = log or log_print, ask or ask_model
    meta = read_meta(path)
    target = profile.interview / path.name
    old = read_text(target) if target.exists() else ""
    kept = questions_part(old)
    kept = old[kept[0]:kept[1]].strip() if kept else ""
    template = settings.STORIES_TEMPLATE if kept else settings.INTERVIEW_TEMPLATE
    start = time.time()
    answer = ask(interview_prompt(profile, path, template), settings.MODEL, settings.INTERVIEW_OPTIONS).strip()
    seconds = round(time.time() - start)
    if kept:
        part = questions_part(answer)                 # модель всё же написала вопросы — оставляем прежние
        answer = (answer[:part[0]] + answer[part[1]:]).strip() if part else answer
        answer += "\n\n" + kept
    info = {"model": current_model(), "prompt": template.name,
            "date": date.today().isoformat(), "chars": len(answer), "seconds": seconds}
    profile.interview.mkdir(exist_ok=True)
    write_text(target,
               f"<!-- {json.dumps(info, ensure_ascii=False)} -->\n"
               f"# Подготовка к интервью: {meta['title']} — {meta['company']}\n\n"
               f"[Вакансия]({meta['link']}) · [Разбор](../разборы/{md_path(path.name)})\n\n"
               f"---\n\n{answer}\n")
    stories = len(re.findall(r"(?m)^## \d", answer))
    part = questions_part(answer)
    asked = len(re.findall(r"(?m)^\s*\d+[.)]\s", answer[part[0]:part[1]])) if part else 0
    log(f"      готово: историй — {stories}, " + ("вопросы работодателю — прежние" if kept else
                                                 f"вопросов работодателю — {asked}") + f" ({seconds} с)")
    return target


def write_questions(profile, path, log=None, ask=None):
    """Вопросы работодателю к уже готовой подготовке (или заново): раздел «Мои вопросы работодателю»
    в файле подготовки заменяется, истории STAR остаются. Возвращает файл."""
    log, ask = log or log_print, ask or ask_model
    target = profile.interview / path.name
    if not target.exists():
        return write_interview(profile, path, log, ask)
    start = time.time()
    answer = ask(interview_prompt(profile, path, settings.QUESTIONS_TEMPLATE), settings.MODEL,
                 settings.QUESTIONS_OPTIONS).strip()
    seconds = round(time.time() - start)
    part = questions_part(answer)
    block = (answer[part[0]:part[1]] if part else f"{QUESTIONS_HEAD}\n{answer}").strip()
    text = read_text(target)
    old = questions_part(text)
    text = (text[:old[0]] + block + "\n\n" + text[old[1]:]).rstrip() + "\n" if old else text.rstrip() + "\n\n" + block + "\n"
    write_text(target, text)
    asked = len(re.findall(r"(?m)^\s*\d+[.)]\s", block))
    log(f"      готово: вопросов — {asked} ({seconds} с)")
    return target


def write_letters(profile, redo=False, log=None, ask=None, summary=True, only=None, among=None):
    """Письма для вакансий с оценкой не ниже порога профиля (минимальная_оценка) и решением «да» или
    «да, но…» (в окне — «возможно»). among — только среди этих вакансий (имена файлов).
    only — новые версии писем для этих вакансий, где письмо уже есть (при любой оценке). Возвращает список писем."""
    log, ask = log or log_print, ask or ask_model
    todo = []
    for path in sorted(profile.results.glob("*.md")):
        meta = read_meta(path)
        if not meta:
            continue
        if only is not None:
            if path.name in set(only) and (profile.letters / path.name).exists():
                todo.append((path, meta))
        elif ((meta["score"] or 0) >= profile.letter_min_score and decision_yes(meta.get("decision"))
                and (among is None or path.name in set(among))
                and (redo or not (profile.letters / path.name).exists())):
            todo.append((path, meta))
    phase(log, f"Пишу сопроводительные письма моделью {current_model()}")
    log(f"Нужно написать: {len(todo)} — " + ("новые версии писем по новому образцу (старые сохранятся в истории)"
        if only is not None else f"для вакансий с оценкой {profile.letter_min_score} и выше и решением «да» или «возможно», "
        "у которых письма ещё нет"))

    resume = profile.read_resume() if todo else ""
    done = []
    for i, (path, meta) in enumerate(todo, 1):
        log(f"[{i}/{len(todo)}] Пишу письмо: {meta['title']} — {meta['company']}")
        done.append(write_letter(profile, path, resume, log, ask))

    if summary:
        write_summary(profile, log)
    return done
