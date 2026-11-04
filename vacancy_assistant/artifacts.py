"""Артефакты вакансии: что ушло работодателю или пришло от него — отправленные версии писем и резюме,
приложенные файлы (тестовое, презентация, оффер), заметки о переписке вне почты.

Папка профиля «артефакты/<имя файла вакансии>/»: тексты — Markdown (видны в Obsidian), файлы — копии
(попадают в резервную копию профиля), опись.json — список: тип, название, дата, файл. Удаление — в Корзину."""
import re
import uuid
from datetime import date, datetime

from .errors import AssistantError
from .textio import read_json, read_text, write_json, write_text

FOLDER, INDEX = "артефакты", "опись.json"
MAX_FILE = 25 * 1024 * 1024
TYPES = {"cover": "Сопроводительное письмо", "referrer": "Сообщение референсеру", "resume": "Резюме под вакансию",
         "file": "Файл", "note": "Заметка о переписке"}
TEXT_TYPES = ("cover", "referrer", "resume", "note")


def folder(profile, path):
    return profile.dir / FOLDER / path.stem


def _index(profile, path):
    return read_json(folder(profile, path) / INDEX, [])


def _save(profile, path, items):
    write_json(folder(profile, path) / INDEX, items)


def _day(when):
    try:
        return date.fromisoformat(when).isoformat() if when else date.today().isoformat()
    except ValueError:
        raise AssistantError("Дата — в виде ГГГГ-ММ-ДД.")


def _free_name(f, name):
    """Имя файла без «/» и служебных символов; занято — «имя (2).pdf»."""
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name).strip(" .") or "файл"
    stem, dot, ext = name.rpartition(".") if "." in name else (name, "", "")
    target, i = f / name, 2
    while target.exists() or name == INDEX:
        name = f"{stem} ({i}){dot}{ext}"
        target, i = f / name, i + 1
    return target


def _add(profile, path, entry, write):
    f = folder(profile, path)
    f.mkdir(parents=True, exist_ok=True)
    entry = {"id": uuid.uuid4().hex[:8], "added": datetime.now().isoformat(timespec="seconds"), **entry}
    target = _free_name(f, entry.pop("name"))
    write(target)
    entry["file"] = target.name
    _save(profile, path, _index(profile, path) + [entry])
    return entry


def add_text(profile, path, kind, title, text, when=None):
    """Текстовый артефакт: отправленная версия письма или резюме, заметка о переписке. Возвращает запись описи."""
    text = (text or "").strip()
    if kind not in TEXT_TYPES:
        raise AssistantError("Неизвестный вид артефакта.")
    if not text:
        raise AssistantError("Текст пустой — нечего сохранять.")
    title = " ".join((title or TYPES[kind]).split())[:80]
    day = _day(when)
    return _add(profile, path, {"type": kind, "title": title, "date": day, "name": f"{day} {title}.md"},
                lambda t: write_text(t, f"# {title}\n\n{day}\n\n---\n\n{text}\n"))


def add_file(profile, path, name, data, when=None, title=""):
    """Приложенный файл — копией в папку артефактов вакансии (не больше MAX_FILE)."""
    if not data:
        raise AssistantError("Файл пустой.")
    if len(data) > MAX_FILE:
        raise AssistantError(f"Файл больше {MAX_FILE // 1024 // 1024} МБ — его в программу не взять. "
                             "Положите его рядом с вакансией сами или приложите уменьшенную копию.")
    name = (name or "файл").split("/")[-1].split("\\")[-1]
    return _add(profile, path, {"type": "file", "title": " ".join((title or name).split())[:80], "date": _day(when),
                                "name": name, "size": len(data)}, lambda t: t.write_bytes(data))


def get(profile, path, aid):
    entry = next((e for e in _index(profile, path) if e["id"] == aid), None)
    if entry is None:
        raise AssistantError("Такого артефакта нет — обновите окно.")
    return entry


def file_path(profile, path, aid):
    return folder(profile, path) / get(profile, path, aid)["file"]


def set_date(profile, path, aid, when):
    items = _index(profile, path)
    for e in items:
        if e["id"] == aid:
            e["date"] = _day(when)
    _save(profile, path, items)


def remove(profile, path, aid, trash):
    """Убирает артефакт: его файл — в Корзину (trash(path)), запись — из описи. Возвращает запись."""
    entry = get(profile, path, aid)
    f = folder(profile, path) / entry["file"]
    if f.exists():
        trash(f)
    _save(profile, path, [e for e in _index(profile, path) if e["id"] != aid])
    return entry


def listing(profile, path):
    """Артефакты вакансии, новые сверху; у текстовых — текст (без заголовка), у файлов — размер."""
    out = []
    for e in _index(profile, path):
        f = folder(profile, path) / e["file"]
        item = {**e, "missing": not f.exists()}
        if e["type"] in TEXT_TYPES and f.exists():
            item["text"] = read_text(f).split("\n---\n", 1)[-1].strip()
        out.append(item)
    return sorted(out, key=lambda e: (e["date"], e.get("added", "")), reverse=True)


def types(profile):
    """Виды артефактов каждой вакансии: {имя файла без .md: [вид, …]} — для колонки таблицы (сколько их)
    и «Статистики» (было ли отправлено сопроводительное письмо)."""
    root = profile.dir / FOLDER
    if not root.exists():
        return {}
    return {d.name: [e["type"] for e in read_json(d / INDEX, [])] for d in root.iterdir() if (d / INDEX).exists()}
