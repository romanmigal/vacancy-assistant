"""Вакансии с любых сайтов — по ссылке или вставленным текстом (hh.ru — по-прежнему в hh.py).

Как читается страница, по порядку:
1. Разметка schema.org JobPosting (её делают многие сайты для поиска Google по вакансиям) — название,
   компания, зарплата, город и описание берутся из неё точно.
2. Иначе — основной текст страницы: без меню, шапки, подвала и скриптов; название — из заголовка <h1>;
   хвост вроде «Похожие вакансии» отрезается.
3. Если человек разрешил разбирать страницы моделью (настройка профиля), модель одним коротким запросом
   находит, какие строки — сама вакансия (без кнопок, хлебных крошек и чужих вакансий), и достаёт
   компанию, зарплату, город и формат работы. Модель отвечает номерами строк, а не пересказом, —
   поэтому текст вакансии остаётся дословным. Нет согласия, нет ключа GigaChat или не запущена
   Ollama — всё берётся со страницы как есть.
Если сайт показывает вакансию только после входа или собирает её скриптами в браузере, текста на
странице почти нет — тогда вакансию можно добавить, вставив её текст (add_text).
Страницу, сохранённую в браузере (⌘S), можно загрузить файлом (add_saved) — без обращения к сети;
так добавляются вакансии с hh.ru, когда поиск на hh выключен.
"""
import html
import json
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from datetime import date

from . import company, dupes, settings
from .errors import AssistantError
from .files import read_vacancy, save_numbered, vacancy_number
from . import hh
from .hh import DescriptionToMarkdown, add_vacancies, phase, vacancy_ids
from .textio import log_print, read_text, write_text

MIN_TEXT = 300                 # меньше — на странице нет текста вакансии (нужен вход или браузер)
MAX_TEXT = 15000               # длиннее — обрезаем: модели хватит, а промпт не раздуется
URL = re.compile(r"https?://[^\s<>\"'«»]+")
DROP = r"script|style|noscript|svg|nav|header|footer|aside|form|iframe|template|button|select"
# С этих строк на странице начинаются чужие вакансии — дальше текст не нужен
TAIL = re.compile(r"(?im)^\W*(ещё варианты|похожие вакансии|другие вакансии|вам (также )?могут подойти|"
                  r"смотрите также|рекомендуемые вакансии|similar jobs)\W*$")


def split_links(text):
    """Ссылки из текста: номера вакансий hh.ru и адреса других сайтов (без дублей, в порядке появления)."""
    urls = [u.rstrip(".,;)") for u in URL.findall(text or "")]
    other = []
    for u in urls:
        if "hh.ru/vacancy/" not in u and "hh.ru" not in urllib.parse.urlsplit(u).netloc and u not in other:
            other.append(u)
    hh_ids = vacancy_ids([text or ""]) if any("hh.ru" in u for u in urls) or not urls else []
    return hh_ids, other


# Известные площадки — по адресу; остальное — «Сайт <компания>» (сайт работодателя)
BOARDS = {"hh.ru": "HH", "career.habr.com": "Хабр Карьера", "linkedin.com": "LinkedIn", "superjob.ru": "SuperJob",
          "rabota.ru": "Работа.ру", "zarplata.ru": "Зарплата.ру", "avito.ru": "Авито", "getmatch.ru": "getmatch",
          "geekjob.ru": "GeekJob", "trudvsem.ru": "Работа России", "t.me": "Telegram"}
LEGAL = r"^(?:ООО|ПАО|ОАО|АО|ЗАО|НАО|АНО|ИП|ГК|ФГУП|МУП|Группа компаний|LLC|Ltd\.?|Inc\.?|JSC)\s+|,?\s+(?:LLC|Ltd\.?|Inc\.?)$"


def company_name(company):
    """Короткое имя компании: без «ПАО», «ООО» и пояснений — «Роял Кредит Банк (группа …)» → «Роял Кредит Банк»."""
    name = re.sub(LEGAL, "", (company or "").strip(), flags=re.I)
    return re.split(r"\s*[(,;]", name)[0].strip(" «»\"")


def people_query(company):
    """Имя компании для поиска людей в LinkedIn и Сетке; '' — искать некого (анонимный работодатель)."""
    name = company_name(company)
    return "" if not name or re.search(r"аноним|не указан", name, re.I) else name


def inn_valid(inn):
    """Контрольные цифры ИНН: 10 цифр — организация, 12 — ИП (две контрольные)."""
    d = [int(c) for c in inn]
    check = lambda k: sum(a * b for a, b in zip(k, d)) % 11 % 10
    if len(d) == 10:
        return check([2, 4, 10, 3, 5, 9, 4, 6, 8]) == d[9]
    return len(d) == 12 and check([7, 2, 4, 10, 3, 5, 9, 4, 6, 8]) == d[10] \
        and check([3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8]) == d[11]


def find_inn(text):
    """ИНН работодателя из текста вакансии: 10 или 12 цифр сразу после слова «ИНН», с верной контрольной суммой."""
    for m in re.finditer(r"ИНН\W{0,5}(\d{10}(?:\d{2})?)(?!\d)", text or "", re.I):
        if inn_valid(m[1]):
            return m[1]
    return ""


def finance_link(company, text=""):
    """Бухгалтерская отчётность компании на сайте ФНС (ГИР БО): по ИНН из вакансии, если есть, иначе по названию.
    Возвращает {"url", "by_inn"} или None — компания скрыта. Сайт ФНС открывает человек, программа туда не ходит."""
    inn, name = find_inn(text), people_query(company)
    if not inn and not name:
        return None
    return {"url": "https://bo.nalog.gov.ru/search?query=" + urllib.parse.quote(inn or name), "by_inn": bool(inn)}


def source(link, company=""):
    """Откуда вакансия: «HH», «Хабр Карьера», «Сайт МТС» (сайт компании), «Вручную» (вставлен текст)."""
    if not re.match(r"https?://", link or ""):
        return "Вручную"
    host = urllib.parse.urlsplit(link).netloc.lower().removeprefix("www.")
    for domain, name in BOARDS.items():
        if host == domain or host.endswith("." + domain):
            return name
    name = company_name(company)
    return f"Сайт {name}" if name and "." not in name and len(name) <= 30 else host


def key(url):
    """Ссылка без хвостов (?utm=…, #…) — по ней узнаём уже добавленную вакансию."""
    p = urllib.parse.urlsplit(url)
    return f"{p.netloc.lower().removeprefix('www.')}{p.path.rstrip('/')}"


class Gone(AssistantError):
    """Страницы больше нет (404 или 410) — вакансию, похоже, сняли."""


_mincifry = None


def mincifry_context():
    """Проверка сертификатов, где к обычным корневым центрам добавлены сертификаты Минцифры (#49).
    Создаётся один раз. Только для чтения страниц вакансий и только после ошибки обычной проверки."""
    global _mincifry
    if _mincifry is None:
        from .cloud import CA_FILE                     # тот же файл, что у GigaChat
        _mincifry = ssl.create_default_context()
        _mincifry.load_verify_locations(cafile=str(CA_FILE))
    return _mincifry


def unknown_issuer(e):
    """Ошибка именно в том, что не знаем, кто выдал сертификат («unable to get local issuer certificate»).
    Просроченный сертификат или сертификат на чужое имя так не обходим."""
    err = getattr(e, "reason", e)
    return isinstance(err, ssl.SSLCertVerificationError) and getattr(err, "verify_code", None) in (19, 20, 21)


def fetch(url, attempts=2, log=None):
    """Страница любого сайта как текст (кодировку берём из ответа сервера или из страницы).
    Сайт подписан сертификатом Минцифры, которого нет в списке Python, — повтор с сертификатами Минцифры."""
    request = urllib.request.Request(url, headers={"User-Agent": settings.USER_AGENT,
                                                   "Accept-Language": "ru,en;q=0.8"})
    error, context = "", None
    for attempt in range(attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=30, context=context) as r:
                raw, charset = r.read(), r.headers.get_content_charset()
            if not charset:
                m = re.search(rb'<meta[^>]+charset=["\']?([\w-]+)', raw[:3000], re.I)
                charset = m.group(1).decode() if m else "utf-8"
            return raw.decode(charset, errors="replace")
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise AssistantError(f"Сайт {urllib.parse.urlsplit(url).netloc} не пускает программу (ответ {e.code}) — "
                                     "добавьте вакансию, вставив её текст.") from e
            if e.code in (404, 410):
                raise Gone(f"Страницы больше нет (ответ {e.code}) — вакансию, похоже, сняли.") from e
            error = f"сайт ответил ошибкой {e.code}"
        except (urllib.error.URLError, OSError) as e:
            if unknown_issuer(e):
                if context is not None:                # и с Минцифры не открылся — повторять бессмысленно
                    raise AssistantError("Сайт подписан сертификатом, которому программа не доверяет — "
                                         "добавьте вакансию сохранённой страницей или текстом.") from e
                (log or (lambda *_: None))("      Сайт подписан сертификатом Минцифры — открываю с ним.")
                context = mincifry_context()
                continue
            error = f"нет связи с сайтом ({getattr(e, 'reason', e)})"
        if attempt + 1 >= attempts and context is None:
            break
    raise AssistantError(f"Не удалось открыть страницу: {error}.")


def read_page(fetch_page, url, log):
    """Страница вакансии; свой fetch получает лог — чтобы сказать про сертификат Минцифры."""
    return fetch_page(url, log=log) if fetch_page is fetch else fetch_page(url)


def clean(text):
    return re.sub(r"\s+", " ", html.unescape(text or "")).replace("\xa0", " ").strip()


def to_markdown(fragment):
    parser = DescriptionToMarkdown()
    parser.feed(fragment)
    return parser.text()


def job_posting(page):
    """Разметка schema.org JobPosting со страницы (в том числе внутри @graph или списка) или None."""
    for block in re.findall(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', page, re.S | re.I):
        try:
            data = json.loads(block.strip())
        except ValueError:
            continue
        items = data if isinstance(data, list) else data.get("@graph", [data]) if isinstance(data, dict) else []
        for item in items:
            kind = item.get("@type") if isinstance(item, dict) else None
            if kind == "JobPosting" or (isinstance(kind, list) and "JobPosting" in kind):
                return item
    return None


def salary_text(base):
    """baseSalary из JobPosting → «от 300 000 до 400 000 RUB в месяц»."""
    if not isinstance(base, dict):
        return clean(str(base)) if base else ""
    value = base.get("value", {})
    value = value if isinstance(value, dict) else {"value": value}
    lo, hi, one = value.get("minValue"), value.get("maxValue"), value.get("value")
    fmt = lambda x: f"{int(float(x)):,}".replace(",", " ")
    parts = ([f"от {fmt(lo)}"] if lo else []) + ([f"до {fmt(hi)}"] if hi else []) + ([fmt(one)] if one and not (lo or hi) else [])
    unit = {"MONTH": "в месяц", "YEAR": "в год", "HOUR": "в час"}.get(str(value.get("unitText", "")).upper(), "")
    return " ".join(parts + [base.get("currency", ""), unit]).strip()


def from_job_posting(jp):
    org = jp.get("hiringOrganization") or {}
    loc = jp.get("jobLocation") or {}
    loc = loc[0] if isinstance(loc, list) and loc else loc
    address = loc.get("address", {}) if isinstance(loc, dict) else {}
    city = address.get("addressLocality", "") if isinstance(address, dict) else clean(str(address))
    return {"title": clean(jp.get("title")), "company": clean(org.get("name") if isinstance(org, dict) else org),
            "salary": salary_text(jp.get("baseSalary")), "where": clean(city),
            "format": "удалённо" if jp.get("jobLocationType") == "TELECOMMUTE" else "",
            "text": to_markdown(html.unescape(jp.get("description", ""))), "posted": hh.posted(json.dumps(jp))}


def main_text(page):
    """Основной текст страницы: <main> или <article>, иначе <body> — без меню, шапки, подвала, скриптов."""
    body = page
    for tag in ("main", "article", "body"):
        m = re.search(rf"<{tag}\b[^>]*>(.*)</{tag}>", page, re.S | re.I)
        if m and len(clean(re.sub(r"<[^>]+>", " ", m.group(1)))) > MIN_TEXT:
            body = m.group(1)
            break
    body = re.sub(rf"<({DROP})\b.*?</\1\s*>", " ", body, flags=re.S | re.I)
    body = re.sub(r"<!--.*?-->", " ", body, flags=re.S)
    return cut_tail(to_markdown(body))


def cut_tail(text):
    """Текст без чужих вакансий внизу страницы («Ещё варианты», «Похожие вакансии»…)."""
    m = next((m for m in TAIL.finditer(text) if m.start() > MIN_TEXT), None)
    return text[:m.start()].rstrip() if m else text


def meta(page, name):
    m = re.search(rf'<meta[^>]+(?:property|name)=["\']{name}["\'][^>]*content=["\']([^"\']*)', page, re.I) or \
        re.search(rf'<meta[^>]+content=["\']([^"\']*)["\'][^>]*(?:property|name)=["\']{name}["\']', page, re.I)
    return clean(m.group(1)) if m else ""


def from_page(page, url):
    # Название: заголовок <h1>, который совпадает с названием страницы (бывают служебные <h1> вроде
    # «Детальная страница вакансии»), иначе — название страницы без хвоста «— Работа в МТС»
    head = meta(page, "og:title") or clean(re.sub(r"<[^>]+>", " ", (re.search(r"<title>(.*?)</title>", page, re.S | re.I) or [None, ""])[1]))
    head_title = re.split(r"\s+[-—|]\s+", head)[0] if head else ""
    h1s = [clean(re.sub(r"<[^>]+>", " ", h)) for h in re.findall(r"<h1\b[^>]*>(.*?)</h1>", page, re.S | re.I)]
    h1s = [h for h in h1s if h]
    from_h1 = next((h for h in h1s if head_title and h.lower() in head_title.lower()), "")
    title = from_h1 or head_title or (h1s[0] if h1s else "")
    site = meta(page, "og:site_name") or urllib.parse.urlsplit(url).netloc.removeprefix("www.")
    # имя сайта — только догадка о компании: модель, если она есть, заменит его на работодателя из текста
    return {"title": title, "company": site, "salary": "", "where": "", "format": "", "text": main_text(page), "posted": hh.posted(page),
            "guess": ["company"] + ([] if from_h1 else ["title"])}       # название не из <h1> — тоже уточнить


FIELDS_PROMPT = """Ответь строго в таком виде, по одной строке, ничего не добавляя:
Название: <должность>
Компания: <работодатель>
Зарплата: <как указано в тексте, или «не указана»>
Город: <город, или «не указан»>
Формат: <офис / гибрид / удалённо, или «не указан»>{lines_field}
Ничего не выдумывай: если поля нет в тексте — так и пиши «не указана» / «не указан».

=== ТЕКСТ ===
{text}"""
EXTRACT_PROMPT = "Ниже текст вакансии с сайта. Выпиши из него поля.\n" + FIELDS_PROMPT
LINES_PROMPT = ("Ниже текст страницы с вакансией, строки пронумерованы. Кроме самой вакансии, на странице бывает "
                "лишнее: меню, кнопки («Поделиться», «Откликнуться»), хлебные крошки, другие вакансии, подвал сайта.\n"
                + FIELDS_PROMPT)
LINES_FIELD = ("\nОписание: строки <первая>–<последняя>\n"
               "В «Описание» — номера первой и последней строки самого текста вакансии: от начала описания "
               "(о компании, задачи) до последней строки требований и условий. Меню, кнопки и другие вакансии не входят.")
MODEL_OPTIONS = {"temperature": 0.1, "num_predict": 200, "num_ctx": 12288}


def numbered(text):
    """Непустые строки с номерами — для модели — и где каждая из них в исходном тексте."""
    lines = text.split("\n")
    where = [i for i, l in enumerate(lines) if l.strip()]
    return "\n".join(f"{n}: {lines[i].strip()}" for n, i in enumerate(where, 1)), lines, where


def ask_fields(text, ask=None, cut=False):
    """Компания, зарплата, город, формат — короткий запрос к модели; cut — ещё и строки самой вакансии
    (поле "text" в ответе — вырезанный текст). None, если модель недоступна."""
    from .model import ask_model
    ask = ask or ask_model
    if cut:
        shown, lines, where = numbered(text)
        prompt = LINES_PROMPT.format(lines_field=LINES_FIELD, text=shown)
    else:
        prompt = EXTRACT_PROMPT.format(lines_field="", text=text[:6000])
    try:
        answer = ask(prompt, settings.MODEL, MODEL_OPTIONS)
    except Exception:                                   # noqa: BLE001 — нет ключа, Ollama не запущена, сеть
        return None
    fields = {}
    for label, k in (("Название", "title"), ("Компания", "company"), ("Зарплата", "salary"),
                     ("Город", "where"), ("Формат", "format")):
        m = re.search(rf"(?m)^[#*\s]*{label}:\**\s*(.+)$", answer)
        value = clean(m.group(1)).strip("«»\"*") if m else ""
        if value and not re.match(r"не указан", value, re.I):
            fields[k] = value
    m = cut and re.search(r"(?m)^[#*\s]*Описание:\**\D*(\d+)\D+?(\d+)", answer)
    if m:
        first, last = int(m.group(1)), int(m.group(2))
        if 1 <= first <= last <= len(where):
            part = "\n".join(lines[where[first - 1]:where[last - 1] + 1]).strip()
            if len(part) >= MIN_TEXT:                    # модель ошиблась номерами — оставляем всё
                fields["text"] = part
    return fields


def vacancy_file(info, url, saved=None):
    saved = saved or date.today().strftime("%d.%m.%Y")
    where = ", ".join(x for x in (info.get("where"), info.get("format")) if x) or "не указано"
    return (f"# {info['title']}\n\n"
            f"**Компания:** {info.get('company') or 'не указана'}  \n"
            f"**Зарплата:** {info.get('salary') or 'не указана'}  \n"
            f"**Где:** {where}  \n"
            f"**Ссылка:** {url or 'нет — текст вставлен вручную'}  \n"
            + (f"**Источник:** {info['via']}  \n" if info.get("via") else "")
            + hh.posted_line(info.get("posted", ""))
            + f"**Сохранено:** {saved}\n\n---\n\n"
            f"{info['text'].strip()}\n")


def save(profile, info, url, log):
    """Записывает вакансию в vacancies/ под следующим номером — так же, как вакансии с hh.ru.
    Та же вакансия уже есть (#13) — ссылка дописывается к ней, возвращает None."""
    same, text = dupes.check(profile, info["title"], info.get("company") or "", vacancy_file(info, url), url, log)
    if same:
        return None
    num, path = save_numbered(profile.vacancies, f"{info['title']} — {info.get('company') or 'не указана'}", text)
    log(f"Сохранил под номером {num:02d}: {info['title']} — {info.get('company') or 'компания не указана'}")
    return path


def complete(info, log, ask=None, use_model=True, cut=False):
    """Недостающие поля и (cut) текст без лишнего — у модели, если человек это разрешил;
    иначе остаётся то, что взято со страницы."""
    if not use_model:
        if cut:
            log("      текст страницы сохранён целиком — убрать с него лишнее может модель, "
                "если разрешить это в «Параметры → Настройки»")
        return info
    if not cut and info.get("salary") and info.get("company") and info.get("where") and info.get("title"):
        return info
    fields = ask_fields(f"{info.get('title', '')}\n\n{info['text']}" if not cut else info["text"], ask, cut)
    if fields is None:
        log("      модель недоступна — название, компания и текст взяты со страницы как есть")
        return info
    if "text" in fields and len(fields["text"]) < len(info["text"]):
        log(f"      модель убрала со страницы лишнее: {len(info['text']) - len(fields['text'])} знаков из {len(info['text'])}")
    for k, v in fields.items():
        if not info.get(k) or k in info.get("guess", []) or k == "text":
            info[k] = v
    return info


def add_pages(profile, urls, log=None, fetch_page=fetch, ask=None, via=""):
    """Скачивает вакансии с других сайтов. via — откуда ссылка («Хабр Карьера (RSS)»), строкой «Источник» в файле.
    Возвращает список новых файлов."""
    log = log or log_print
    phase(log, f"Скачиваю вакансии с сайтов: {len(urls)}")
    saved = []
    for url in urls:
        site = urllib.parse.urlsplit(url).netloc.removeprefix("www.")
        existing = next((p for p in sorted(profile.vacancies.glob("*.md")) if key(url) in key_text(read_text(p))), None) \
            if profile.vacancies.exists() else None
        if existing:
            log(f"Пропускаю {url}: уже есть в списке под номером {vacancy_number(existing):02d}")
            continue
        log(f"Читаю вакансию на {site}…")
        try:
            page = read_page(fetch_page, url, log)
        except AssistantError as e:
            log(f"      {e}")
            continue
        jp = job_posting(page)
        info = from_job_posting(jp) if jp else from_page(page, url)
        if len(info["text"]) < MIN_TEXT or not info["title"]:
            log(f"      На странице почти нет текста вакансии — сайт показывает её только в браузере или после входа. "
                f"Добавьте вакансию, вставив её текст.")
            continue
        info["text"] = info["text"][:MAX_TEXT]
        if via:
            info["via"] = via
        log("      описание взято из разметки вакансии" if jp else "      описание взято из текста страницы")
        path = save(profile, complete(info, log, ask, profile.llm_pages, cut=not jp), url, log)
        if path:
            saved.append(path)
    return saved


def refresh(profile, path, log=None, fetch_page=fetch, ask=None, seen=None):
    """Перечитывает вакансию с другого сайта (или вставленный текст) по текущим настройкам: разбор
    страницы моделью — если он разрешён. Номер, имя файла и дата сохранения — прежние, поэтому разбор,
    письмо, заметка и статус остаются при вакансии. Возвращает True, если текст вакансии обновлён.
    seen — словарь: в seen["actual"] — открыта ли вакансия на сайте (actual.OPEN / GONE; не узнали — None)."""
    seen = {} if seen is None else seen
    seen["actual"] = None
    log = log or log_print
    text, old = read_vacancy(path)
    url = old["link"] if re.match(r"https?://", old["link"]) else ""
    if url:
        log(f"Перечитываю вакансию на {urllib.parse.urlsplit(url).netloc.removeprefix('www.')}…")
        try:
            page = read_page(fetch_page, url, log)
        except AssistantError as e:
            if isinstance(e, Gone):
                seen["actual"] = "closed"
            log(f"      {e} Оставляю прежний текст.")
            return False
        jp = job_posting(page)
        info = from_job_posting(jp) if jp else from_page(page, url)
        if len(info["text"]) < MIN_TEXT or not info["title"]:
            log("      На странице почти нет текста вакансии — оставляю прежний текст.")
            return False
        seen["actual"] = "open"                         # страница отдала вакансию — она открыта
        info["text"] = info["text"][:MAX_TEXT]
        info["posted"] = info.get("posted") or old["posted"]    # сайт перестал отдавать дату — оставляем прежнюю
        cut = not jp
    else:                                               # вставленный текст: страницы нет — чистим то, что сохранено
        if not profile.llm_pages:
            return False
        where = re.search(r"\*\*Где:\*\*[ \t]*(.*?)[ \t]*$", text, re.M)
        info = {"title": old["title"], "company": old["company"],
                "salary": "" if old["salary"].startswith("не указан") else old["salary"],
                "where": "" if not where or where.group(1).startswith("не указан") else where.group(1), "format": "",
                "text": text.split("\n---\n", 1)[-1].strip(), "guess": [], "posted": old["posted"]}
        cut = True
    info = complete(info, log, ask, profile.llm_pages, cut)
    via = re.search(r"\*\*Источник:\*\*[ \t]*(.*?)[ \t]*$", text, re.M)     # из RSS-ленты (#39) — остаётся
    if via:
        info["via"] = via.group(1)
    write_text(path, vacancy_file(info, url, old["saved"] or None))
    log("      текст вакансии обновлён")
    return True


def key_text(text):
    """Ключи всех ссылок в файле вакансии — чтобы узнать уже добавленную."""
    return " ".join(key(u) for u in URL.findall(text))


def add_text(profile, text, url="", log=None, ask=None):
    """Вакансия из вставленного текста (сайт не отдаёт страницу программе). Возвращает файл."""
    log = log or log_print
    text = (text or "").strip()
    if len(text) < 100:
        raise AssistantError("Вставьте текст вакансии целиком — название, обязанности, требования.")
    phase(log, "Добавляю вакансию из текста")
    first = next((l.strip(" #*") for l in text.splitlines() if l.strip()), "")
    info = {"title": first[:120], "company": "", "salary": "", "where": "", "format": "", "text": text[:MAX_TEXT],
            "guess": ["title"]}                                   # первая строка — только догадка о названии
    info = complete(info, log, ask, profile.llm_pages, cut=True)
    return save(profile, info, url.strip(), log)


def add_any(profile, text, log=None, fetch_page=None, ask=None):
    """«Добавить вакансию по ссылке»: ссылки hh.ru — если поиск на hh включён, остальные — с их сайтов."""
    log = log or log_print
    hh_ids, other = split_links(text)
    if not hh_ids and not other:
        raise AssistantError("Не нашёл ссылок на вакансии.")
    if hh_ids and not profile.hh_auto:
        if not other:
            hh.require_auto(profile)                     # понятная ошибка — без обращения к hh.ru
        log(f"Ссылки hh.ru пропускаю ({len(hh_ids)}): поиск на hh.ru выключен. Сохраните эти вакансии в браузере "
            "и загрузите страницы файлом или вставьте их текст.")
        hh_ids = []
    saved = []
    if hh_ids:
        saved += add_vacancies(profile, hh_ids, log, **({"fetch_page": fetch_page} if fetch_page else {}))
    if other:
        saved += add_pages(profile, other, log, fetch_page or fetch, ask)
    return saved


def page_url(page):
    """Адрес сохранённой страницы: пометка браузера «saved from url», canonical или og:url; нет — ""."""
    for rx in (r"<!--\s*saved from url=\(\d+\)(\S+?)\s*-->", r'<link[^>]+rel=["\']canonical["\'][^>]*href=["\']([^"\']+)',
               r'<link[^>]+href=["\']([^"\']+)["\'][^>]*rel=["\']canonical["\']'):
        m = re.search(rx, page, re.I)
        if m and m.group(1).startswith("http"):
            return html.unescape(m.group(1))
    url = meta(page, "og:url")
    return url if url.startswith("http") else ""


def hh_page_id(page, url):
    """Номер вакансии hh.ru на сохранённой странице: из её адреса, из данных страницы или из первой ссылки."""
    m = (re.search(r"hh\.ru/vacancy/(\d+)", url) or re.search(r'"vacancyId"\s*:\s*"?(\d+)', page)
         or re.search(r"hh\.ru/vacancy/(\d+)", page))
    return m.group(1) if m else ""


def add_saved(profile, page, name="", log=None, ask=None):
    """Вакансия со страницы, сохранённой в браузере (файл .html), — без обращения к сети.
    Страница hh.ru читается как при скачивании с hh, другие сайты — как add_pages. Возвращает файл."""
    log = log or log_print
    phase(log, f"Добавляю вакансию из сохранённой страницы{f' «{name}»' if name else ''}")
    url = page_url(page)
    if 'data-qa="vacancy-title"' in page:                    # страница hh.ru
        vid = hh_page_id(page, url)
        if not vid:
            raise AssistantError("Это страница hh.ru, но номера вакансии на ней нет — сохраните страницу самой вакансии.")
        existing = next((p for p in sorted(profile.vacancies.glob("*.md")) if f"hh.ru/vacancy/{vid}" in read_text(p)), None) \
            if profile.vacancies.exists() else None
        if existing:
            # Та же вакансия ещё раз — обновить сведения о работодателе: рейтинг hh есть только в сохранённой странице
            msg = f"Эта вакансия уже есть в списке под номером {vacancy_number(existing):02d}."
            raise AssistantError(msg + (" Рейтинг и сведения о работодателе с hh обновлены."
                                        if company.from_page(profile, existing, page) else ""))
        title, firm, text = hh.vacancy_markdown(page, vid)
        if not title:
            raise AssistantError("Не удалось прочитать вакансию на сохранённой странице hh.ru.")
        same, text = dupes.check(profile, title, firm, text, f"https://hh.ru/vacancy/{vid}", log)
        if same:
            return None
        profile.vacancies.mkdir(exist_ok=True)
        num, path = save_numbered(profile.vacancies, f"{title} — {firm}", text)
        company.from_page(profile, path, page)
        hh.remember_seen(profile, [(vid, f"{title} — {firm}")], "страницей")
        log(f"Сохранил под номером {num:02d}: {title} — {firm}")
        return path
    if url and profile.vacancies.exists():
        existing = next((p for p in sorted(profile.vacancies.glob("*.md")) if key(url) in key_text(read_text(p))), None)
        if existing:
            raise AssistantError(f"Эта вакансия уже есть в списке под номером {vacancy_number(existing):02d}.")
    jp = job_posting(page)
    info = from_job_posting(jp) if jp else from_page(page, url)
    if len(info["text"]) < MIN_TEXT or not info["title"]:
        raise AssistantError("В сохранённой странице почти нет текста вакансии. Сохраните страницу целиком "
                             "(«Веб-страница полностью») или вставьте текст вакансии.")
    info["text"] = info["text"][:MAX_TEXT]
    log("      описание взято из разметки вакансии" if jp else "      описание взято из текста страницы")
    profile.vacancies.mkdir(exist_ok=True)
    return save(profile, complete(info, log, ask, profile.llm_pages, cut=not jp), url, log)
