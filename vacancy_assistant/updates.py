"""Проверка обновлений: раз в день — файл latest.json последнего релиза в публичном репозитории релизов.

latest.json: {"version": "0.5.0", "url": "…/releases/tag/v0.5.0", "notes": "что нового"} — собирает build.yml по тегу v*;
«что нового» — раздел версии из docs/Что нового.md (release_notes).
Запрос — простой GET без параметров: о пользователе ничего не отправляется. Программа сама ничего не скачивает
и не ставит — окно показывает плашку со ссылкой. Недоступный адрес — тихо, без ошибки (до следующего дня).
Выключатель — «Параметры → Настройки → Обновления»; настройка и последний ответ — в «профили/обновления.json».
Кнопка «Проверить обновления» — проверка сразу, не дожидаясь следующего дня, и даже при выключенной автоматической.
"""
import json
import re
import urllib.request
from datetime import date

from . import __version__, settings
from .textio import read_json, read_text, write_json

FILE = "обновления.json"                 # {"enabled": true, "checked": "2026-10-29", "latest": {…} или null}
CHANGES = "docs/Что нового.md"            # что нового по версиям: окно, справка и описание релиза


def parse_version(v):
    """«v0.10.0» → (0, 10, 0); не версия — None."""
    m = re.fullmatch(r"v?(\d+(?:\.\d+)*)", str(v or "").strip())
    return tuple(int(x) for x in m.group(1).split(".")) if m else None


def newer(latest, current=__version__):
    a, b = parse_version(latest), parse_version(current)
    if a is None or b is None:
        return False
    width = max(len(a), len(b))
    return a + (0,) * (width - len(a)) > b + (0,) * (width - len(b))


def fetch_latest(url=None):
    request = urllib.request.Request(url or settings.UPDATES_URL, headers={"User-Agent": "job-search-assistant"})
    with urllib.request.urlopen(request, timeout=5) as r:
        return json.loads(r.read().decode("utf-8"))


def clean(data):
    """Только нужные поля и только ссылка https — ответ не должен подсунуть окну что-то лишнее."""
    if not isinstance(data, dict) or not parse_version(data.get("version")):
        return None
    url = str(data.get("url") or "")
    return {"version": str(data["version"]).lstrip("v"), "url": url if url.startswith("https://") else settings.RELEASES_PAGE,
            "notes": str(data.get("notes") or "")[:4000]}


def release_notes(version, text=None):
    """Раздел версии из docs/Что нового.md — пункты без заголовка (для описания релиза); нет раздела — ""."""
    text = read_text(settings.PROJECT_DIR / CHANGES) if text is None else text
    m = re.search(rf"^## {re.escape(str(version).lstrip('v'))}(?![\d.])[^\n]*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    return m.group(1).strip() if m else ""


def load(folder):
    return {"enabled": True, "checked": "", "latest": None, **read_json(folder / FILE, {})}


def set_enabled(folder, enabled):
    write_json(folder / FILE, {**load(folder), "enabled": bool(enabled)})


def state(folder, fetch=fetch_latest, today=None, current=__version__, force=False):
    """Состояние для окна; если проверка включена и сегодня ещё не проверяли — проверяет.
    force — кнопка «Проверить обновления»: проверяет сейчас, а неудача — в "problem" (автоматическая молчит)."""
    cfg = load(folder)
    today = (today or date.today()).isoformat()
    problem = ""
    if force or (cfg["enabled"] and cfg["checked"] != today):
        try:
            latest = clean(fetch())
        except Exception:
            latest, problem = None, "Не удалось проверить: нет связи с GitHub. Попробуйте позже."
        else:
            if latest is None:
                problem = "Не удалось проверить: GitHub ответил непонятно. Попробуйте позже."
        if latest:
            cfg["latest"] = latest                   # неудача — прежний ответ остаётся
        cfg["checked"] = today
        write_json(folder / FILE, cfg)
    latest = cfg["latest"] if cfg["enabled"] or force else None
    out = {"enabled": cfg["enabled"], "current": current, "latest": latest,
           "newer": bool(latest and newer(latest["version"], current))}
    return {**out, "problem": problem} if force else out
