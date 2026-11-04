"""hh.ru: скачивание вакансий и поиск. Читаем обычные страницы сайта, как браузер:
официального API для соискателей нет (hh прекратил его поддержку 15.12.2025).

Соглашение hh.ru запрещает автоматический сбор данных скриптами (пп. 5.1.6, 5.1.7, 8.6, 8.8), поэтому
программа ходит на hh.ru только с явного согласия человека — настройка профиля «hh_авто» (Profile.hh_auto).
Каждый запрос идёт через guarded(): там проверка согласия, пауза между запросами и дневной предел.
Без согласия вакансию с hh.ru можно добавить сохранённой страницей (sites.add_saved) или текстом."""
import html
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from html.parser import HTMLParser

from . import settings
from .errors import AssistantError
from .files import save_numbered, vacancy_number
from .textio import append_text, log_print, read_json, read_text, write_json, write_text

ANONYMOUS = "Анонимный работодатель"
DAY_LIMIT = 300                    # запросов к hh.ru в день на профиль
PAUSE = 1                          # секунд между запросами — не меньше
COUNTER_FILE = "hh-запросы.json"   # {"дата": "2026-10-26", "запросов": 120}
OFF = ("Поиск на hh.ru выключен: программа не открывает hh.ru сама. Откройте вакансию в браузере и сохраните "
       "страницу (⌘S или Ctrl+S), затем перетащите файл в окно программы или нажмите «Загрузить файл…». "
       "Или вставьте текст вакансии. Включить поиск можно в «Параметры → Настройки».")
ASK = ("Поиск на hh.ru ждёт вашего решения: включён он или нет. Выберите в окне программы — "
       "до этого программа не открывает hh.ru.")


class DayLimit(AssistantError):
    """Дневной предел запросов к hh.ru исчерпан — дальше не ходим, до завтра."""


def require_auto(profile):
    """Ходить на hh.ru можно только с согласия человека; иначе — понятная ошибка, без обращения к сети."""
    if profile.hh_state == "ask":
        raise AssistantError(ASK)
    if not profile.hh_auto:
        raise AssistantError(OFF)


def guarded(profile, fetch_page):
    """fetch_page с проверками профиля: согласие, пауза не меньше PAUSE между запросами (с настоящим hh.ru)
    и не больше DAY_LIMIT запросов в день — счётчик в папке профиля."""
    if getattr(fetch_page, "guarded", False):
        return fetch_page
    require_auto(profile)
    last = [0.0]

    def get(url):
        f = profile.dir / COUNTER_FILE
        data = read_json(f) if f.exists() else {}
        today = date.today().isoformat()
        n = data.get("запросов", 0) if data.get("дата") == today else 0
        if n >= DAY_LIMIT:
            raise DayLimit(f"За сегодня программа уже сделала {DAY_LIMIT} запросов к hh.ru — это дневной предел, "
                           "чтобы не нагружать сайт. Продолжить можно завтра; вакансии можно добавлять сохранённой "
                           "страницей или текстом.")
        write_json(f, {"дата": today, "запросов": n + 1})
        wait = last[0] + PAUSE - time.monotonic()
        if fetch_page is fetch and wait > 0:
            time.sleep(wait)
        try:
            return fetch_page(url)
        finally:
            last[0] = time.monotonic()
    get.guarded = True
    return get


def fetch(url, attempts=3):
    """Страница hh.ru как текст. Сбой сети — ещё две попытки с паузой, потом понятная ошибка."""
    request = urllib.request.Request(url, headers={"User-Agent": settings.USER_AGENT})
    for attempt in range(attempts):
        try:
            return urllib.request.urlopen(request, timeout=30).read().decode("utf-8")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return ""                              # вакансия удалена
            error = f"hh.ru ответил ошибкой {e.code}"
        except (urllib.error.URLError, OSError) as e:
            error = f"нет связи с hh.ru ({getattr(e, 'reason', e)})"
        if attempt + 1 < attempts:
            time.sleep(5 * (attempt + 1))
    raise AssistantError(f"Не удалось открыть страницу: {error}. Проверьте интернет и выключите VPN.")


class DescriptionToMarkdown(HTMLParser):
    """Превращает HTML-описание вакансии в простой markdown."""
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag == "li":
            self.parts.append("\n- ")
        elif tag in ("p", "div", "ul", "ol", "h1", "h2", "h3"):
            self.parts.append("\n\n")
        elif tag == "br":
            self.parts.append("\n")
        elif tag in ("strong", "b"):
            self.parts.append("**")

    def handle_endtag(self, tag):
        if tag in ("strong", "b"):
            self.parts.append("**")

    def handle_data(self, data):
        self.parts.append(data)

    def text(self):
        t = "".join(self.parts).replace("\xa0", " ")
        t = re.sub(r"\*\*\s*\*\*", "", t)            # пустой жирный
        t = re.sub(r"[ \t]+", " ", t)
        t = re.sub(r"\n[ \t]+", "\n", t)
        t = re.sub(r"\n{3,}", "\n\n", t)
        t = re.sub(r"(\n- [^\n]*)\n\n(?=- )", r"\1\n", t)   # пункты списка подряд
        t = re.sub(r"\n- \n+", "\n- ", t)
        return t.strip()


ARCHIVED_TAG = re.compile(r"\s*(?:Вакансия\s+)?в\s+архиве(?:\s+с\s+\d{1,2}\s+[а-яё]+(?:\s+\d{4})?)?\s*$", re.I)
ARCHIVED_FIELD = "На hh.ru"                  # строка шапки вакансии: «**На hh.ru:** вакансия в архиве»


def page_field(page, qa):
    """Текст элемента страницы hh.ru с атрибутом data-qa."""
    m = re.search(rf'data-qa="{re.escape(qa)}"[^>]*>(.*?)</(?:h1|span|div|p|a)>', page, re.S)
    if not m:
        return ""
    text = html.unescape(re.sub(r"<[^>]+>", " ", m.group(1)))
    return re.sub(r"\s+", " ", text).replace("\xa0", " ").strip()


def page_description(page):
    """Блок описания вакансии: ищем его начало и закрывающий </div> по балансу."""
    i = page.find('data-qa="vacancy-description"')
    if i < 0:
        return ""
    start, depth, end = page.rfind("<", 0, i), 0, len(page)
    for m in re.finditer(r"<(/?)div\b[^>]*>", page[start:]):
        depth += -1 if m.group(1) else 1
        if depth == 0:
            end = start + m.end()
            break
    parser = DescriptionToMarkdown()
    parser.feed(page[start:end])
    return parser.text()


MONTHS = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря")
POSTED_FIELD = "Опубликовано"
DATE_POSTED = re.compile(r'"datePosted"\s*:\s*"(\d{4})-(\d{2})-(\d{2})')
_GAP = r"(?:\s|&nbsp;|<[^>]*>)"                  # пробелы и теги между частями даты в разметке hh
POSTED_LINE = re.compile(rf"Вакансия опубликована{_GAP}*(\d{{1,2}}){_GAP}+({'|'.join(MONTHS)}){_GAP}+(\d{{4}})")


def posted(page):
    """Дата публикации вакансии — «20.10.2026» или "": datePosted из разметки JobPosting,
    иначе строка hh «Вакансия опубликована 20 октября 2026 в Москве»."""
    m = DATE_POSTED.search(page or "")
    if m:
        return f"{m.group(3)}.{m.group(2)}.{m.group(1)}"
    m = POSTED_LINE.search(page or "")
    return f"{int(m.group(1)):02d}.{MONTHS.index(m.group(2)) + 1:02d}.{m.group(3)}" if m else ""


def posted_line(value):
    return f"**{POSTED_FIELD}:** {value}  \n" if value else ""


def set_posted(path, value):
    """Обновить дату публикации в файле вакансии (hh поднимает вакансию — дата меняется). True — если поменялась."""
    if not value:
        return False
    text = read_text(path)
    old = re.search(rf"^\*\*{POSTED_FIELD}:\*\*[ \t]*(.*?)[ \t]*$", text, re.M)
    if old and old.group(1) == value:
        return False
    if old:
        text = text[:old.start()] + posted_line(value).rstrip("\n") + text[old.end():]
    else:
        text = re.sub(r"^(\*\*Сохранено:\*\*)", lambda m: posted_line(value) + m.group(1), text, count=1, flags=re.M)
    write_text(path, text)
    return True


def vacancy_markdown(page, vid, saved=None):
    """Файл вакансии: шапка (название, компания, зарплата…) и описание. None — если страница не прочиталась."""
    title = page_field(page, "vacancy-title")
    if not title:
        return None, None, None
    # У закрытой вакансии hh дописывает к заголовку плашку «В архиве с 27 октября 2026» — в название она не входит
    title, archived = ARCHIVED_TAG.subn("", title)
    title = title.strip() or page_field(page, "vacancy-title")
    from .actual import GONE, hh_state                 # actual сам зовёт hh — импорт здесь, без цикла
    archived = archived or hh_state(page) == GONE
    company = page_field(page, "vacancy-company-name") or ANONYMOUS     # работодатель скрыт
    from .company import header_line, hh_employer      # company сам читает вакансии через files — импорт здесь
    saved = saved or date.today().strftime("%d.%m.%Y")
    text = (f"# {title}\n\n"
            f"**Компания:** {company}  \n"
            f"**Зарплата:** {page_field(page, 'vacancy-salary') or 'не указана'}  \n"
            f"**Опыт:** {page_field(page, 'vacancy-experience')}  \n"
            f"**Где:** {page_field(page, 'vacancy-view-location') or page_field(page, 'vacancy-view-raw-address') or 'не указано'}  \n"
            + header_line(hh_employer(page))
            + f"**Ссылка:** https://hh.ru/vacancy/{vid}  \n"
            + (f"**{ARCHIVED_FIELD}:** вакансия в архиве  \n" if archived else "")
            + posted_line(posted(page))
            + f"**Сохранено:** {saved}\n\n---\n\n"
            f"{page_description(page)}\n")
    return title, company, text


def vacancy_ids(texts):
    """Номера вакансий из ссылок любого вида: хвосты вроде ?from=...&hhtmFrom=... отбрасываются."""
    ids = []
    for text in texts:
        found = re.findall(r"hh\.ru/vacancy/(\d+)", text) or re.findall(r"\b(\d{6,})\b", text)
        for v in found:
            if v not in ids:
                ids.append(v)
    return ids


def phase(log, title):
    """Заголовок этапа в логе: «▶ …». Окно программы показывает по нему, что сейчас идёт."""
    log("")
    log(f"▶ {title}")


def remember_seen(profile, items, mark):
    """Дописывает вакансии в просмотрено.txt: номер, дата, пометка, название."""
    today = date.today().strftime("%d.%m.%Y")
    append_text(profile.seen, "".join(f"{vid}\t{today}\t{mark}\t{title}\n" for vid, title in items))


def recheck_filtered(profile, days=14, today=None):
    """Отсеянные по названию за последние days дней, которые проходят отбор теперь (правила поменялись):
    [{"id", "date", "title"}], новые сверху. Вакансии, которые потом всё-таки взяли или добавили по ссылке, — не в счёт."""
    if not profile.seen.exists():
        return []
    since = (today or date.today()).toordinal() - days
    rows, taken = {}, set()
    for line in read_text(profile.seen).splitlines():
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        vid, day, mark, title = parts[:4]
        if not vid.isdigit():                      # из RSS-лент — перепроверка только для hh.ru
            continue
        if mark != "отсеяна":
            taken.add(vid)
            continue
        try:
            when = date(*map(int, reversed(day.split("."))))
        except ValueError:
            continue
        if when.toordinal() >= since:
            rows[vid] = {"id": vid, "date": when.isoformat(), "title": title}
    if profile.vacancies.is_dir():                 # уже в списке (добавили по ссылке после отсева) — не предлагаем
        for f in profile.vacancies.rglob("*.md"):
            taken.update(re.findall(r"hh\.ru/vacancy/(\d+)", read_text(f)[:2000]))
    out = [r for vid, r in rows.items() if vid not in taken and profile.title_fits(r["title"])]
    return sorted(out, key=lambda r: r["date"], reverse=True)


def add_vacancies(profile, ids, log=None, fetch_page=fetch, titles=None, from_search=False):
    """Скачивает вакансии по номерам в vacancies/ профиля. Возвращает список новых файлов.

    Добавленное по ссылке запоминается в просмотрено.txt, чтобы поиск потом не считал его новым.
    Найденное поиском (from_search) запоминается как «взята» — только то, до чего дошла очередь: если
    дневной предел оборвал скачивание, остальные остаются новыми и скачаются при следующем поиске."""
    log = log or log_print
    titles = titles or {}
    if not ids:
        raise AssistantError("Не нашёл ссылок на вакансии hh.ru (ни в аргументах, ни в буфере обмена).")
    fetch_page = guarded(profile, fetch_page)
    phase(log, f"Скачиваю вакансии с hh.ru: {len(ids)}")
    profile.vacancies.mkdir(exist_ok=True)
    saved, added, taken = [], [], []
    for i, vid in enumerate(ids):
        existing = next((p for p in sorted(profile.vacancies.glob("*.md")) if vid in read_text(p)), None)
        if existing:
            log(f"Пропускаю {titles.get(vid) or vid}: уже есть в списке под номером {vacancy_number(existing):02d}")
            added.append((vid, existing.stem[3:]))
            taken.append(vid)
            continue
        try:
            page = fetch_page(f"https://hh.ru/vacancy/{vid}")
        except DayLimit as e:
            log(str(e))
            if from_search:
                log(f"Не скачаны: {len(ids) - i} — скачаю при следующем поиске")
            break
        except AssistantError as e:
            taken.append(vid)                          # сбой или закрыта — как раньше, снова не берём
            log(f"Не удалось скачать вакансию {titles.get(vid) or vid}: {e}")
            continue
        taken.append(vid)
        title, company, text = vacancy_markdown(page, vid)
        if not title:
            log(f"Не удалось прочитать вакансию {vid} (включён VPN или вакансия закрыта)")
            continue
        from .dupes import check                          # та же вакансия с другого сайта
        same, text = check(profile, title, company, text, f"https://hh.ru/vacancy/{vid}", log)
        if same:
            added.append((vid, f"{title} — {company}"))
            continue
        num, path = save_numbered(profile.vacancies, f"{title} — {company}", text)
        from .company import from_page
        from_page(profile, path, page, fetch_page, log)   # агентство ли (признак hh) и рейтинг работодателя
        saved.append(path)
        added.append((vid, f"{title} — {company}"))
        log(f"Скачал и сохранил под номером {num:02d}: {title} — {company}")
    if from_search:
        remember_seen(profile, [(v, titles.get(v, "")) for v in taken], "взята")
    else:
        seen = set(re.findall(r"^(\d+)", read_text(profile.seen), re.M)) if profile.seen.exists() else set()
        remember_seen(profile, [(v, t) for v, t in added if v not in seen], "по ссылке")
    return saved


def parse_search_page(page):
    """Страница выдачи hh.ru → [(номер, название)]."""
    found = re.findall(r'data-qa="serp-item__title"[^>]*href="[^"]*/vacancy/(\d+)[^"]*"[^>]*>(.*?)</a>', page, re.S)
    return [(vid, html.unescape(re.sub(r"<[^>]+>", "", title)).strip()) for vid, title in found]


def search_url(query, where, days, page_no=0):
    return (f"https://hh.ru/search/vacancy?text={urllib.parse.quote(query)}&{where}"
            f"&search_period={days}&page={page_no}")


def read_queries(profile):
    return [l.strip() for l in read_text(profile.searches).splitlines() if l.strip() and not l.startswith("#")]


MAX_PAGES = 100            # hh показывает не больше 2000 вакансий на запрос — 100 страниц по 20


def search_pages(query, where, days, fetch_page, sleep):
    """Все страницы выдачи по запросу: читаем, пока страницы не кончатся. Возвращает [(номер, название)]
    и число прочитанных страниц."""
    results, ids = [], set()
    for page_no in range(MAX_PAGES):
        page_results = [(v, t) for v, t in parse_search_page(fetch_page(search_url(query, where, days, page_no)))
                        if v not in ids]
        sleep(1)   # не торопим hh.ru
        if not page_results:              # страницы кончились (или hh повторил прошлую)
            return results, page_no
        results += page_results
        ids.update(v for v, _ in page_results)
    return results, MAX_PAGES


def plural(n, one, few, many):
    """1 вакансия, 2 вакансии, 5 вакансий."""
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} {one}"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return f"{n} {few}"
    return f"{n} {many}"


def search(profile, log=None, fetch_page=fetch, sleep=time.sleep, limit=None):
    """Ищет по запросам из поиски.txt, отсеивает по названию, запоминает просмотренное,
    скачивает подходящее. limit — разовый лимит вместо настройки профиля (первый поиск).
    Возвращает список новых файлов вакансий."""
    log = log or log_print
    fetch_page = guarded(profile, fetch_page)
    seen = set(re.findall(r"^(\d+)", read_text(profile.seen), re.M)) if profile.seen.exists() else set()
    queries = read_queries(profile)
    phase(log, f"Ищу на hh.ru: {plural(len(queries), 'запрос', 'запроса', 'запросов')} × "
               f"{len(profile.search_where)} (где искать), вакансии за {profile.search_days} дн.")
    found, failed = {}, 0
    for query in queries:
        for label, where in profile.search_where:
            try:
                results, pages = search_pages(query, where, profile.search_days, fetch_page, sleep)
            except DayLimit:
                raise
            except AssistantError as e:                  # один запрос не прочитался — остальные ищем дальше
                log(f"Ищу позиции «{query}», {label}: не получилось — {e}")
                failed += 1
                continue
            more = f" ({plural(pages, 'страница', 'страницы', 'страниц')})" if pages > 1 else ""
            log(f"Ищу позиции «{query}», {label}, нашёл {plural(len(results), 'вакансию', 'вакансии', 'вакансий')}{more}")
            if pages >= MAX_PAGES:
                log(f"  hh показывает не больше {MAX_PAGES * 20} вакансий — уточните запрос «{query}»")
            for vid, title in results:
                found.setdefault(vid, title)

    if failed and not found:
        raise AssistantError("hh.ru не ответил ни на один запрос. Проверьте интернет и выключите VPN.")
    new = {vid: title for vid, title in found.items() if vid not in seen}
    fit = [vid for vid, title in new.items() if profile.title_fits(title)]
    phase(log, "Отсеиваю по названию")
    log(f"Всего разных вакансий: {len(found)} (одна вакансия могла найтись по нескольким запросам)")
    log(f"Уже видел раньше: {len(found) - len(new)}, новых: {len(new)}")
    log(f"Подходят по названию: {len(fit)}, отсеяно: {len(new) - len(fit)}")
    dropped = [title for vid, title in new.items() if vid not in fit]
    if dropped:                                    # чтобы было видно, что именно режет отбор по названию
        log("  например, отсеяны: " + "; ".join(f"«{t}»" for t in dropped[:5]) + (" …" if len(dropped) > 5 else ""))
    later = []
    cap = limit or profile.search_limit
    if cap and len(fit) > cap:                                       # лимит за один поиск — остальные в следующий раз
        fit, later = fit[:cap], fit[cap:]
        why = "первый поиск" if limit else "настройка «сколько новых вакансий за поиск»"
        log(f"За один поиск беру {len(fit)} ({why}), остальные {len(later)} — при следующем поиске")
    for vid in fit:
        log(f"  + {new[vid]}")

    # Запоминаем всё новое, чтобы в следующий раз не смотреть повторно; отложенные по лимиту — не запоминаем,
    # взятые запоминает скачивание — по мере того, как до них доходит очередь
    remember_seen(profile, [(vid, title) for vid, title in new.items() if vid not in fit and vid not in later],
                  "отсеяна")
    saved = add_vacancies(profile, fit, log, fetch_page, titles=new, from_search=True) if fit else []
    return saved
