"""Шаблоны сопроводительного письма (#53): до трёх образцов с названиями, один — по умолчанию.

Основной шаблон (id 1) — прежний «образец письма.txt»: старые профили ничего не переносят. Остальные —
«образец письма 2.txt», «образец письма 3.txt». Названия и шаблон по умолчанию — в профиль.json.
История правок у каждого шаблона своя (criteria_history, which="letter" или "letter:2")."""
from . import criteria_history
from .errors import AssistantError
from .textio import read_text, write_text

KEY, DEFAULT_KEY = "шаблоны_письма", "шаблон_письма_по_умолчанию"
MAX = 3
MAIN = {"id": 1, "название": "Основной"}


def _items(profile):
    return profile.config.get(KEY) or [dict(MAIN)]


def file(profile, tid):
    return profile.letter_example if tid == 1 else profile.dir / f"образец письма {tid}.txt"


def which(tid):
    """Ключ истории шаблона: у основного — прежний «letter», чтобы его история осталась на месте."""
    return "letter" if tid == 1 else f"letter:{tid}"


def default_id(profile):
    ids = [i["id"] for i in _items(profile)]
    tid = profile.config.get(DEFAULT_KEY, 1)
    return tid if tid in ids else ids[0]


def get(profile, tid=None):
    """Шаблон по id (нет такого или не указан — по умолчанию): {id, name, default, text}."""
    items = _items(profile)
    item = next((i for i in items if i["id"] == tid), None) or next(i for i in items if i["id"] == default_id(profile))
    f = file(profile, item["id"])
    return {"id": item["id"], "name": item["название"], "default": item["id"] == default_id(profile),
            "text": read_text(f).strip() if f.exists() else ""}


def all_templates(profile):
    return [get(profile, i["id"]) for i in _items(profile)]


def save(profile, tid, name, text, default=False, source="изменён вручную"):
    """Новый (tid=None) или правка шаблона; прежний текст и новый — в историю этого шаблона. Возвращает id."""
    name, text = " ".join((name or "").split()), (text or "").strip()
    if not name:
        raise AssistantError("Введите название шаблона.")
    if len(name) > 40:
        raise AssistantError("Название шаблона — не длиннее 40 символов.")
    if not text:
        raise AssistantError("Шаблон пустой — вставьте текст письма-образца.")
    items = _items(profile)
    if any(i["название"].lower() == name.lower() and i["id"] != tid for i in items):
        raise AssistantError(f"Шаблон «{name}» уже есть.")
    if tid is None:
        if len(items) >= MAX:
            raise AssistantError(f"Шаблонов — не больше {MAX}.")
        tid = max(i["id"] for i in items) + 1
        items.append({"id": tid, "название": name})
    else:
        item = next((i for i in items if i["id"] == tid), None)
        if item is None:
            raise AssistantError("Такого шаблона нет — обновите окно.")
        item["название"] = name
    f = file(profile, tid)
    if f.exists() and read_text(f).strip() != text:
        criteria_history.record(profile, read_text(f), "до правки", which=which(tid))
    write_text(f, text + "\n")
    criteria_history.record(profile, text, source, kind="manual", which=which(tid))
    profile.config[KEY] = items
    if default:
        profile.config[DEFAULT_KEY] = tid
    profile.save_config()
    return tid


def set_default(profile, tid):
    if tid not in [i["id"] for i in _items(profile)]:
        raise AssistantError("Такого шаблона нет — обновите окно.")
    profile.config[KEY] = _items(profile)
    profile.config[DEFAULT_KEY] = tid
    profile.save_config()


def delete(profile, tid, trash):
    """Удаляет шаблон (кроме основного): файл и его историю — в Корзину (trash(path)), не насовсем."""
    if tid == 1:
        raise AssistantError("Основной шаблон удалить нельзя — его можно переписать.")
    items = _items(profile)
    if tid not in [i["id"] for i in items]:
        raise AssistantError("Такого шаблона нет — обновите окно.")
    for path in (file(profile, tid), profile.dir / criteria_history.folder_name(which(tid))):
        if path.exists():
            trash(path)
    profile.config[KEY] = [i for i in items if i["id"] != tid]
    if profile.config.get(DEFAULT_KEY) == tid:
        profile.config[DEFAULT_KEY] = 1
    profile.save_config()
