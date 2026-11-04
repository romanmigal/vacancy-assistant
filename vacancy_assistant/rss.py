"""Вакансии из RSS-лент (#39): Хабр Карьера и GeekJob.

Ленты — официальный способ подписки, их чтение условиями сайтов не запрещено. Хабр Карьера ищет по запросам
из поиски.txt (до 50 последних вакансий на запрос), GeekJob отдаёт 100 последних без фильтра — отбирает
программа: по названию, затем модель. Из ленты берутся название, компания и ссылка; полный текст —
со страницы вакансии, так же как «добавить по ссылке». Каждую ленту читаем не чаще раза в час; что уже
видели — в просмотрено.txt с номером вида «habr:1000168654», чтобы не путать с номерами hh.ru.
"""
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime

from . import sites
from .errors import AssistantError
from .hh import phase, plural, read_queries, remember_seen
from .textio import log_print, read_json, read_text, write_json

FEEDS = {"habr": "Хабр Карьера", "geekjob": "GeekJob"}
HABR_URL = "https://career.habr.com/vacancies/rss?q={q}"
GEEKJOB_URL = "https://geekjob.ru/vacancies/rss"
EVERY = 3600                   # секунд: каждую ленту — не чаще раза в час
PAUSE = 1                      # секунд между запросами к одному сайту
STATE_FILE = "rss.json"        # когда какую ленту читали: {"habr": "2026-11-03T15:00:00"}
HABR_TITLE = re.compile(r"^Требуется «(.*)»(?:\s*\(([^()]*)\))?\s*$", re.S)
BARE_AMP = re.compile(r"&(?!#\d+;|#x[0-9a-fA-F]+;|\w+;)")
COMPANY_PREFIX = re.compile(r"^(?:Компания|Клмпания)\s+")      # в ленте GeekJob — с опечаткой


def enabled(profile):
    """Включённые ленты профиля: ["habr", "geekjob"]."""
    on = profile.config.get("rss") or {}
    return [k for k in FEEDS if on.get(k)]


def set_enabled(profile, feeds):
    profile.config["rss"] = {k: bool((feeds or {}).get(k)) for k in FEEDS}
    profile.save_config()


def clean_link(link):
    """Ссылка без меток ленты (?utm_source=rss): по ней же ищем, нет ли вакансии в списке."""
    parts = urllib.parse.urlsplit(link.strip())
    query = [(k, v) for k, v in urllib.parse.parse_qsl(parts.query) if not k.startswith("utm_")]
    return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query), fragment=""))


def parse(xml, feed):
    """Элементы ленты: [{"id", "title", "company", "link", "where"}]."""
    xml = BARE_AMP.sub("&amp;", xml.strip())              # GeekJob пишет «Martsun & Partners» без экранирования
    try:
        root = ET.fromstring(xml.encode("utf-8"))
    except ET.ParseError as e:
        raise AssistantError(f"Лента {FEEDS[feed]} не читается: {e}") from e
    items = []
    for it in root.iter("item"):
        text = lambda tag: " ".join((it.findtext(tag) or "").split())
        title, where, link = text("title"), "", clean_link(text("link"))
        if feed == "habr":
            m = HABR_TITLE.match(title)
            if m:
                title, where = m.group(1), m.group(2) or ""
        if not title or not link:
            continue
        items.append({"id": f"{feed}:{text('guid') or link}", "title": title,
                      "company": COMPANY_PREFIX.sub("", text("author")), "link": link, "where": where})
    return items


def last_read(profile):
    return read_json(profile.dir / STATE_FILE, {})


def due(profile, feed, now=None):
    """Пора ли читать ленту: прошёл час с прошлого чтения. Возвращает (да/нет, сколько минут ждать)."""
    when = last_read(profile).get(feed)
    if not when:
        return True, 0
    passed = ((now or datetime.now()) - datetime.fromisoformat(when)).total_seconds()
    return passed >= EVERY, max(1, int((EVERY - passed) // 60) + 1)


def urls(profile, feed):
    if feed == "geekjob":
        return [GEEKJOB_URL]
    return [HABR_URL.format(q=urllib.parse.quote(q)) for q in read_queries(profile)] if profile.searches.exists() else []


def search(profile, log=None, fetch_page=sites.fetch, ask=None, sleep=time.sleep, limit=None, now=None):
    """Читает включённые ленты, отсеивает по названию и уже виденное, скачивает подходящее.
    Возвращает список новых файлов вакансий."""
    log = log or log_print
    feeds = enabled(profile)
    if not feeds:
        return []
    now = now or datetime.now()
    seen = set(re.findall(r"^(\S+)\t", read_text(profile.seen), re.M)) if profile.seen.exists() else set()
    phase(log, "Читаю ленты вакансий: " + ", ".join(FEEDS[f] for f in feeds))
    found, read = {}, last_read(profile)
    for feed in feeds:
        ok, wait = due(profile, feed, now)
        if not ok:
            log(f"{FEEDS[feed]}: лента читалась меньше часа назад — следующее чтение через {wait} мин")
            continue
        links = urls(profile, feed)
        if not links:
            log(f"{FEEDS[feed]}: нет поисковых запросов (поиски.txt) — пропускаю")
            continue
        got, failed = 0, 0
        for i, url in enumerate(links):
            if i:
                sleep(PAUSE)
            try:
                items = parse(sites.read_page(fetch_page, url, log), feed)
            except AssistantError as e:
                log(f"{FEEDS[feed]}: не получилось прочитать ленту — {e}")
                failed += 1
                continue
            got += len(items)
            for item in items:
                found.setdefault(item["id"], {**item, "feed": feed})
        if failed < len(links):
            read[feed] = now.isoformat(timespec="seconds")
        log(f"{FEEDS[feed]}: в ленте {plural(got, 'вакансия', 'вакансии', 'вакансий')}")
    write_json(profile.dir / STATE_FILE, read)
    new = {k: v for k, v in found.items() if k not in seen}
    fit = [k for k, v in new.items() if profile.title_fits(v["title"])]
    log(f"Новых: {len(new)}, подходят по названию: {len(fit)}, отсеяно: {len(new) - len(fit)}")
    later = []
    if limit and len(fit) > limit:
        fit, later = fit[:limit], fit[limit:]
        log(f"Из лент беру {len(fit)}, остальные {len(later)} — при следующем чтении, если ещё будут в ленте")
    remember_seen(profile, [(k, v["title"]) for k, v in new.items() if k not in fit and k not in later], "отсеяна")
    for k in fit:
        log(f"  + {new[k]['title']} — {new[k]['company'] or 'компания не указана'}")
    saved = []
    for feed in feeds:                        # полный текст — со страницы вакансии, как «добавить по ссылке»
        mine = [k for k in fit if new[k]["feed"] == feed]
        if mine:
            saved += sites.add_pages(profile, [new[k]["link"] for k in mine], log, fetch_page, ask, via=f"{FEEDS[feed]} (RSS)")
            remember_seen(profile, [(k, new[k]["title"]) for k in mine], "взята")
    return saved
