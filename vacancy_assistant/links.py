"""«Где искать вакансии» (#32): общий список сайтов, каналов и агентств из ссылки.json и свои ссылки профиля.
Программа ничего по этим ссылкам не скачивает — их открывает сам человек в браузере."""
import re
import uuid
from datetime import date
from pathlib import Path

from .errors import AssistantError
from .textio import read_json, write_json

BUILTIN = Path(__file__).resolve().parent / "ссылки.json"
FILE = "ссылки.json"                                  # свои ссылки — в папке профиля
REQUIRED = ("группа", "название", "адрес", "описание", "сферы", "проверено")
MAX_OWN = 100
FAVORITES = "любимые_ссылки"                          # в профиль.json: адреса любимых сайтов, по порядку добавления
DEFAULT_FAVORITES = ["https://hh.ru"]

# Сферы ссылок и как узнать их в профиле: по «для кого» из разбора и словам «про сферу» из поиска
SPHERES = {
    "ИТ": r"\b(ит|it|ai)\b|информацион|технологи|разработ|программ|цифров|digital|\bcto\b|\bcio\b|devops",
    "Аналитика": r"аналит|\bdata\b|данны|\bml\b",
    "Продукт": r"продукт|проджект|product|project",
    "Маркетинг": r"маркет|\bsmm\b|реклам|\bpr\b|бренд|медиа",
    "Финансы": r"бух|финанс|аудит|налог|экономи|казначе",
}


def load_builtin(path=BUILTIN):
    """Общий список; ошибка в файле — сразу понятным текстом (файл правят руками)."""
    data = read_json(path)
    groups = {g["ключ"] for g in data["группы"]}
    for i, item in enumerate(data["ссылки"], 1):
        missing = [k for k in REQUIRED if k not in item]
        if missing:
            raise ValueError(f"ссылки.json, ссылка {i}: нет полей {', '.join(missing)}")
        if item["группа"] not in groups:
            raise ValueError(f"ссылки.json, «{item['название']}»: неизвестная группа {item['группа']}")
        if not item["адрес"].startswith("https://"):
            raise ValueError(f"ссылки.json, «{item['название']}»: адрес не https")
        if set(item["сферы"]) - set(SPHERES):
            raise ValueError(f"ссылки.json, «{item['название']}»: неизвестная сфера")
        date.fromisoformat(item["проверено"])
    return data


def profile_spheres(profile):
    """Сферы профиля — из мастера: «в сфере «…»» или «ИТ-руководителей» и слова «про сферу» в названии."""
    spec = profile.config["поиск"].get("название_про_сферу", {})
    text = " ".join([profile.config["разбор"].get("для_кого", ""), *spec.get("слова", []), *spec.get("части", [])])
    found = [s for s, rx in SPHERES.items() if re.search(rx, text, re.I)]
    if profile.it_field and "ИТ" not in found:
        found.insert(0, "ИТ")
    return found


def own(profile):
    return read_json(profile.dir / FILE, [])


def favorite_urls(profile):
    return list(profile.config.get(FAVORITES, DEFAULT_FAVORITES))


def favorites(profile, data=None):
    """Любимые сайты — для списка в шапке: название и адрес из общего списка или своих ссылок."""
    data = data or load_builtin()
    names = {i["адрес"]: i["название"] for i in data["ссылки"] + own(profile)}
    return [{"name": names[u], "url": u} for u in favorite_urls(profile) if u in names]


def set_favorite(profile, url, on):
    urls = [u for u in favorite_urls(profile) if u != url]
    if on:
        known = {i["адрес"] for i in load_builtin()["ссылки"] + own(profile)}
        if url not in known:
            raise AssistantError("Такой ссылки нет в списке — обновите окно.")
        urls.append(url)
    profile.config[FAVORITES] = urls
    profile.save_config()
    return favorites(profile)


def for_profile(profile):
    """Группы по порядку файла: ссылки сферы профиля и общие; ссылки других сфер — отдельно (в окне свёрнуты)."""
    data, mine = load_builtin(), profile_spheres(profile)
    public = lambda i: {"name": i["название"], "url": i["адрес"], "about": i["описание"], "spheres": i["сферы"],
                        "auto": i.get("автоматически", ""), "checked": i["проверено"]}
    groups = []
    for g in data["группы"]:
        items = [i for i in data["ссылки"] if i["группа"] == g["ключ"]]
        fits = lambda i: not i["сферы"] or set(i["сферы"]) & set(mine)
        groups.append({"key": g["ключ"], "name": g["название"], "auto": g.get("автоматически", ""),
                       "items": [public(i) for i in items if fits(i)],
                       "other": [public(i) for i in items if not fits(i)]})
    return {"groups": groups, "own": own(profile), "spheres": mine,
            "favorites": favorites(profile, data), "favorite_urls": favorite_urls(profile)}


def add(profile, name, url, about=""):
    name, url, about = " ".join(name.split()), url.strip(), " ".join(about.split())
    if not name:
        raise AssistantError("Введите название ссылки.")
    if len(name) > 80 or len(about) > 300:
        raise AssistantError("Название — не длиннее 80 символов, описание — не длиннее 300.")
    if not re.match(r"https?://[^\s/]+\.[^\s]+$", url):
        raise AssistantError("Адрес должен начинаться с https:// или http://, например https://t.me/канал")
    items = own(profile)
    if len(items) >= MAX_OWN:
        raise AssistantError(f"Своих ссылок — не больше {MAX_OWN}.")
    if any(i["адрес"].rstrip("/") == url.rstrip("/") for i in items):
        raise AssistantError("Такая ссылка уже есть.")
    items.append({"id": uuid.uuid4().hex[:8], "название": name, "адрес": url, "описание": about,
                  "добавлено": date.today().isoformat()})
    write_json(profile.dir / FILE, items)
    return items


def delete(profile, link_id):
    """Удаляет свою ссылку; если она была в любимых — и оттуда."""
    gone = [i["адрес"] for i in own(profile) if i["id"] == link_id]
    items = [i for i in own(profile) if i["id"] != link_id]
    write_json(profile.dir / FILE, items)
    if gone and gone[0] in favorite_urls(profile):
        set_favorite(profile, gone[0], False)
    return items
