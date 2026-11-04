"""Актуальность вакансии: открыта ли она ещё на сайте. Проверяется только по кнопке «Разобрать заново»
в карточке — сама программа вакансии не перепроверяет.

Итог — в свойствах файла разбора, рядом с этапами (видно и правится в Obsidian):
    проверено: 2026-10-27       когда проверяли последний раз — и для открытой, и для закрытой
    закрыта: 2026-10-27         вакансию сняли (нет свойства — открыта)
hh.ru — только при включённом поиске на hh (hh.guarded: согласие, пауза, дневной предел). Признаки закрытия:
у hh — страница 404 или в данных вакансии "status": {"archived": true} (или "disabled": true), у других сайтов —
ответ 404 или 410. Фразу «Вакансия в архиве» искать нельзя: она есть в словаре интерфейса на каждой странице hh.
"""
import re
from datetime import date

from . import hh
from .errors import AssistantError
from .files import read_prop, set_prop

CHECKED, CLOSED = "проверено", "закрыта"
OPEN, GONE = "open", "closed"             # итог проверки; None — проверить не удалось
HH_STATUS = re.compile(r'"status"\s*:\s*\{\s*"archived"\s*:\s*(true|false)\s*,\s*"disabled"\s*:\s*(true|false)')


def hh_state(page):
    """Страница вакансии hh.ru → OPEN или GONE; пустая — 404, вакансию удалили. Нет данных о статусе (заглушка,
    другая вёрстка) — None: не знаем, а не «закрыта»."""
    if not page:
        return GONE
    m = HH_STATUS.search(page.replace("&#34;", '"').replace("&quot;", '"'))
    return None if not m else GONE if "true" in m.groups() else OPEN


def check_hh(profile, url, fetch_page, log, on_page=None):
    """Открыта ли вакансия на hh.ru: OPEN, GONE или None (поиск на hh выключен, предел, нет связи).
    on_page(страница, get) — что ещё взять со скачанной страницы (сведения о работодателе); get — тот же fetch с проверками."""
    if not profile.hh_auto or profile.hh_state == "ask":
        log("Актуальность на hh.ru не проверялась — поиск на hh выключен.")
        return None
    try:
        get = hh.guarded(profile, fetch_page)
        page = get(url)
    except AssistantError as e:                 # дневной предел, нет связи — разбор всё равно делаем
        log(f"Актуальность на hh.ru не проверена: {e}")
        return None
    if on_page:
        on_page(page, get)
    state = hh_state(page)
    if state is None:
        log("Актуальность на hh.ru не проверена: на странице нет данных о статусе вакансии.")
    return state


def read(path):
    """{"checked": "2026-10-27" или "", "closed": "2026-10-27" или ""} — для таблицы и карточки."""
    if not path.exists():
        return {"checked": "", "closed": ""}
    return {"checked": read_prop(path, CHECKED), "closed": read_prop(path, CLOSED)}


def record(path, state, when=None):
    """Записать итог проверки в разбор. None — не проверили: прежний итог остаётся как был."""
    if state is None or not path.exists():
        return
    day = (when or date.today()).isoformat()
    set_prop(path, CHECKED, day)
    if state == GONE:
        if not read_prop(path, CLOSED):         # дата — когда впервые увидели закрытой
            set_prop(path, CLOSED, day)
    elif read_prop(path, CLOSED):               # снова открыта — пометку снимаем
        set_prop(path, CLOSED, "")
