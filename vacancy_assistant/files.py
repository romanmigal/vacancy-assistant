"""Форматы файлов: вакансия, разбор (паспорт + ответ модели), свойства Obsidian, имена файлов."""
import json
import re
import threading
from pathlib import Path

from . import answer
from .textio import read_text, write_text

NOTE_PROP = "заметка"     # заметка к вакансии — свойство в файле её разбора
REFERRER_PROP = "референсер"   # через кого в компании подать резюме — тоже свойство разбора
REFERRER_ID_PROP = "референсер_контакт"   # какой это контакт из трекера (пусто — вписан вручную)

# Текст файлов разбора — с запоминанием: таблица берёт из одного файла паспорт и пять-шесть свойств, и без
# запоминания каждый файл читался ~10 раз. Ключ — путь, время изменения и размер: файл поменялся — читаем заново
_TEXTS, _TEXTS_MAX, _TEXTS_LOCK = {}, 4096, threading.Lock()


def cached_text(path):
    st = Path(path).stat()
    key = (str(path), st.st_mtime_ns, st.st_size)
    with _TEXTS_LOCK:
        if key in _TEXTS:
            return _TEXTS[key]
    text = read_text(path)
    with _TEXTS_LOCK:
        if len(_TEXTS) >= _TEXTS_MAX:
            _TEXTS.clear()
        _TEXTS[key] = text
    return text


def read_vacancy(path):
    """Возвращает текст вакансии и поля из её шапки (компания, зарплата, ссылка, дата сохранения)."""
    text = read_text(path)

    def field(name):
        m = re.search(rf"\*\*{name}:\*\*[ \t]*(.*?)[ \t]*$", text, re.M)   # только своя строка
        return m.group(1) if m else ""

    title = text.splitlines()[0].lstrip("# ").strip()
    return text, {"title": title, "company": field("Компания"),
                  "salary": field("Зарплата"), "link": field("Ссылка"), "saved": field("Сохранено"), "posted": field("Опубликовано"),
                  "more": field("Ещё ссылки"), "maybe": field("Возможно, дубль"),
                  "employer": field("Работодатель на hh"), "where": field("Где")}


def strip_service(text):
    """Убирает из файла служебное: блок свойств и строку-паспорт <!-- {…} -->."""
    text = re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.S)
    return re.sub(r"^<!-- .* -->\n", "", text, flags=re.M).strip()


def analysis_body(text):
    """Ответ модели из файла разбора — без заголовка и строки со ссылками (они уже есть в окне)."""
    text = strip_service(text)
    return re.sub(r"\A# .*\n+(\[Вакансия\].*\n+)?", "", text).strip()


def parse_answer(text):
    """Оценки и решение из ответа модели: {score, can, want, decision} — разбор ответа в answer.py."""
    return answer.result(text)


def decision_yes(text):
    """«да», «да, но с оговорками» → True; «нет» → False; иначе None."""
    text = (text or "").strip().lower()
    return True if text.startswith("да") else False if text.startswith("нет") else None


def decision_word(text):
    """Решение одним словом: «да», «возможно» (= «да, но с оговорками»), «нет»; пусто — если решения нет."""
    yes = decision_yes(text)
    if yes is None:
        return ""
    return "нет" if not yes else "возможно" if "оговор" in text or "возможно" in text else "да"


def say_decision(text):
    """Решение для журнала и Сводки: «да, но с оговорками» — «возможно», непонятное — как есть."""
    return decision_word(text) or (text or "?")


def read_meta(path):
    """«Паспорт» разбора — JSON из строки <!-- … --> (после блока свойств, если он есть)."""
    m = re.search(r"^<!-- (\{.*\}) -->$", cached_text(path), re.M)
    return json.loads(m.group(1)) if m else None


def strengths(text):
    """Сильные стороны из разбора — опора для письма: пункты списком."""
    return "\n".join(f"- {x}" for x in answer.parse(text)["strengths"])


def requirements(text, limit=8):
    """Требования вакансии из разбора, которые подтверждает резюме (✅), — опора для письма: пункты списком.
    Требования с ❌ и строки без отметки (пояснения к оценке) не идут."""
    items = [r["text"] for r in answer.parse(text)["requirements"] if r["ok"] and "✅" in r["text"]]
    return "\n".join(f"- {x}" for x in items[:limit])


def md_path(path):
    """Путь для markdown-ссылки: кодируем пробелы и скобки, кириллицу оставляем читаемой.
    Разделители — всегда «/», и на Windows тоже."""
    path = str(path).replace("\\", "/")
    for ch, code in ((" ", "%20"), ("(", "%28"), (")", "%29"), ("[", "%5B"), ("]", "%5D")):
        path = path.replace(ch, code)
    return path


def safe_name(name):
    """Имя файла, которое работает на Mac и Windows и не ломает ссылки Meta Bind и markdown:
    без [ ] , & и символов, запрещённых в именах файлов; без точки и пробела в конце (Windows)."""
    name = name.replace("[", "(").replace("]", ")").replace("&", " и ").replace(",", "")
    name = re.sub(r'[\\/:*?"<>|«»#^\x00-\x1f]', "", name)
    return re.sub(r"\s{2,}", " ", name).strip().rstrip(". ")


_LOCKS, _LOCKS_GUARD = {}, threading.Lock()


def save_numbered(folder, name, text):
    """Записывает вакансию под следующим номером папки: «07 Название — Компания.md». Номер выбирается
    и файл пишется под замком папки — две задачи (окно, две очереди) не займут один номер.
    Возвращает (номер, файл)."""
    with _LOCKS_GUARD:
        lock = _LOCKS.setdefault(str(Path(folder).resolve()), threading.Lock())
    with lock:
        Path(folder).mkdir(exist_ok=True)
        num = max(numbered_files(folder), default=0) + 1
        path = Path(folder) / f"{safe_name(f'{num:02d} {name}')[:110].strip()}.md"
        write_text(path, text)
        return num, path


def yaml_scalar(raw):
    """Значение свойства как его пишет Obsidian: просто текст, "в двойных" или 'в одинарных' кавычках."""
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] == '"':
        return json.loads(raw)                      # \" и \n внутри — как в JSON
    if len(raw) >= 2 and raw[0] == raw[-1] == "'":
        return raw[1:-1].replace("''", "'")
    return raw


def frontmatter(path):
    """Блок свойств «---…---» в начале файла (с переводом строки) или пустая строка."""
    if not path.exists():
        return ""
    m = re.match(r"---\n.*?\n---\n", cached_text(path), re.S)
    return m.group(0) if m else ""


def read_prop(path, prop):
    """Текст свойства из блока свойств разбора ('' если пусто или нет)."""
    m = re.search(rf"^{prop}:[ \t]*(.*)$", frontmatter(path), re.M)
    if not m:
        return ""
    try:
        value = yaml_scalar(m.group(1))
    except ValueError:
        value = m.group(1)
    return "" if value in ("null", "~") else value


def read_note(path):
    """Текст свойства «заметка» из разбора ('' если пусто)."""
    return read_prop(path, NOTE_PROP)


def ensure_note_prop(path):
    """Добавляет в разбор пустое свойство «заметка», чтобы в Obsidian было поле, куда писать."""
    text = read_text(path)
    fm = frontmatter(path)
    if re.search(rf"^{NOTE_PROP}:", fm, re.M):
        # Пустое значение Obsidian пишет как null, а поле VIEW показывает слово «null» — меняем на ""
        fixed = re.sub(rf"^{NOTE_PROP}:[ \t]*(null|~)?[ \t]*$", f'{NOTE_PROP}: ""', fm, flags=re.M)
        if fixed != fm:
            write_text(path, fixed + text[len(fm):])
        return
    if fm:
        text = fm[:-4] + f'{NOTE_PROP}: ""\n---\n' + text[len(fm):]
    else:
        text = f'---\n{NOTE_PROP}: ""\n---\n' + text
    write_text(path, text)


def set_prop(path, prop, text):
    """Записывает однострочное свойство в разбор (нет такого — добавляет в конец блока свойств)."""
    ensure_note_prop(path)
    text = " ".join((text or "").split())           # одна строка, как в поле Obsidian
    fm = frontmatter(path)
    line = f"{prop}: {json.dumps(text, ensure_ascii=False)}"
    if re.search(rf"^{prop}:", fm, re.M):
        fixed = re.sub(rf"^{prop}:.*$", lambda m: line, fm, count=1, flags=re.M)
    else:
        fixed = fm[:-4] + line + "\n---\n"
    write_text(path, fixed + read_text(path)[len(fm):])


def set_note(path, text):
    """Записывает заметку к вакансии в свойство разбора — то же поле, что правит Obsidian."""
    set_prop(path, NOTE_PROP, text)


def vacancy_number(path):
    """«13 ИТ-директор….md» → 13."""
    return int(re.match(r"\d+", path.name).group(0))


def numbered_files(folder):
    """{номер: файл} для «NN …md» в папке. Номер — все цифры до пробела: после 99 идёт 100, а не «10»."""
    found = ((re.match(r"(\d+) ", f.name), f) for f in Path(folder).glob("*.md"))
    return {int(m.group(1)): f for m, f in found if m}
