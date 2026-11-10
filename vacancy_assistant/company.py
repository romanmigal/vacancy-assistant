"""О компании вакансии: агентство или работодатель, рейтинг и отзывы с hh, прошлые вакансии.

Агентство — посредник: настоящий работодатель скрыт, референсеры и отчётность — по другой компании.
Признаки по порядку надёжности: ваша пометка (на компанию, для всех её вакансий), признак hh у работодателя,
название («кадровое агентство», Hays, Antal…), фразы в описании («для нашего клиента»).

На странице вакансии рейтинг hh дорисовывает уже в браузере — он есть только в странице, сохранённой из
браузера (⌘S). При включённом поиске на hh программа берёт рейтинг со страницы работодателя (hh.ru/employer/…):
там он есть сразу; не чаще раза в RATING_DAYS дней на работодателя, запрос — в дневной предел. Хранится не в тексте вакансии, а в компании.json: текст вакансии уходит в модель,
и рейтинг не должен влиять на оценку. В шапке вакансии — только ссылка на работодателя на hh.
"""
import html
import re
from datetime import date

from . import contacts
from .errors import AssistantError
from .files import numbered_files, read_vacancy
from .textio import read_json, write_json, write_text

FILE = "компании.json"          # {"agency": {ключ компании: true/false}, "hh": {номер работодателя: {…}}}
EMPLOYER_FIELD = "Работодатель на hh"
RATING_DAYS = 30               # рейтинг со страницы работодателя — не чаще
HH_AGENCY = {"AGENCY": "кадровое агентство", "PRIVATE_RECRUITER": "частный рекрутер"}

AGENCY_NAME = re.compile(
    r"кадров|рекрут|recruit|staffing|\bstaff\b|executive search|head ?hunt|хедхант|подбор[а-я]* персонала|"
    r"hr[- ]агентств|агентств[а-я]* (?:по )?подбор|\bhays\b|\bantal\b|kelly services|келли сервис|\bancor\b|анкор|"
    r"get experts|spencer stuart|korn ?ferry|michael page|page executive|coleman|cornerstone|egon zehnder|heidrick|"
    r"russell reynolds|odgers|amrop|intersearch|интерсерч", re.I)
AGENCY_TEXT = re.compile(
    r"(?:для |у )?наш(?:его|ему|им|ем)? клиент(?:а|у|ом|е)?\b|компани[яиюей]+[- ]клиент|по поручению клиента|"
    r"в интересах клиента|наш(?:его|ему)? заказчик(?:а|у)?\b|кадровое агентство|рекрутинговое агентство", re.I)


def load(profile):
    data = read_json(profile.dir / FILE, {})
    return {"agency": data.get("agency", {}), "hh": data.get("hh", {})}


def save(profile, data):
    write_json(profile.dir / FILE, data)


# --- hh: работодатель на странице вакансии

def hh_employer(page):
    """Работодатель на странице вакансии hh: {id, category, rating, reviews, site, it — ИТ-аккредитация}. Чего нет на странице — None."""
    m = re.search(r'data-qa="vacancy-company-name"[^>]*href="[^"]*?/employer/(\d+)'
                  r'|href="[^"]*?/employer/(\d+)[^"]*"[^>]*data-qa="vacancy-company-name"', page)
    if not m:
        return None
    flat = page.replace("&#34;", '"').replace("&quot;", '"')
    cat = re.search(r'"category"\s*:\s*"(COMPANY|AGENCY|PRIVATE_RECRUITER|PROJECT_DIRECTOR)"', flat)
    site = re.search(r'"companySiteUrl"\s*:\s*"([^"\s<>]{4,200})"', flat)
    it = _it(flat)
    rating = re.search(r'data-qa="employer-review-small-widget-total-rating"[^>]*>\s*(?:<[^>]+>\s*)*(\d+(?:[.,]\d+)?)', page)
    i = page.find('data-qa="employer-review-small-widget-review-count-action"')      # число — во вложенных тегах
    near = html.unescape(re.sub(r"<[^>]+>", " ", page[i:i + 1500])) if i >= 0 else ""
    reviews = re.search(r"(\d[\d\s]*?)\s*отзыв", near)
    return {"id": m.group(1) or m.group(2), "category": cat.group(1) if cat else None,
            "rating": float(rating.group(1).replace(",", ".")) if rating else None,
            "reviews": int(re.sub(r"\D", "", reviews.group(1))) if reviews else None,
            "site": _site(site.group(1)) if site else None, "it": it}


def _it(flat):
    """ИТ-аккредитация работодателя (Минцифры) — так её отмечает hh: True, False или None — на странице нет."""
    m = re.search(r'"accreditedITEmployer"\s*:\s*(true|false)', flat)
    return m.group(1) == "true" if m else None


def _site(url):
    """Сайт работодателя из данных hh: «www.x.ru» → «https://www.x.ru»; не похоже на адрес — None."""
    url = url.replace("\\/", "/").strip()
    url = url if re.match(r"https?://", url, re.I) else "https://" + url
    return url if re.match(r"https?://[\w.-]+\.[a-zа-яё]{2,}(?:[/:?#]|$)", url, re.I) else None


def employer_rating(page):
    """Страница работодателя hh: {rating, reviews, site}. Общий рейтинг — «totalRating» после списка отзывов
    (у каждого отзыва свой «totalRating», за ним идут «ratings»)."""
    flat = page.replace("&#34;", '"').replace("&quot;", '"')
    rating = re.search(r'"totalRating"\s*:\s*"?(\d+(?:\.\d+)?)"?\s*,\s*"services"', flat)
    count = re.search(r'"reviewsCount"\s*:\s*(\d+)', flat)
    site = re.search(r'"companySiteUrl"\s*:\s*"([^"\s<>]{4,200})"', flat)
    return {"rating": float(rating.group(1)) if rating else None, "reviews": int(count.group(1)) if count else None,
            "site": _site(site.group(1)) if site else None, "it": _it(flat)}


def fetch_rating(profile, emp, get, log, today=None):
    """Рейтинг со страницы работодателя — только при включённом поиске на hh; get — fetch с проверками (hh.guarded)."""
    today = today or date.today()
    if not emp or not profile.hh_auto or profile.hh_state == "ask":
        return
    old = load(profile)["hh"].get(emp, {})
    if old.get("rating_date") and (today - date.fromisoformat(old["rating_date"])).days < RATING_DAYS:
        return
    try:
        info = employer_rating(get(f"https://hh.ru/employer/{emp}"))
    except AssistantError as e:                     # предел, нет связи — вакансия всё равно сохраняется
        log(f"      рейтинг работодателя на hh не обновлён: {e}")
        return
    data = load(profile)
    cur = data["hh"].setdefault(emp, {})
    cur.update(rating=info["rating"], reviews=info["reviews"], rating_date=today.isoformat())
    if info["site"] and not cur.get("site"):
        cur["site"] = info["site"]
    if info["it"] is not None:
        cur["it"] = info["it"]
    save(profile, data)
    if info["rating"] is not None:
        log(f"      рейтинг работодателя на hh: {info['rating']} ({info['reviews'] or 0} отз.)")


def header_line(info):
    """Строка шапки вакансии со ссылкой на работодателя — пусто, если работодатель скрыт."""
    return f"**{EMPLOYER_FIELD}:** https://hh.ru/employer/{info['id']}  \n" if info else ""


def remember_hh(profile, info, name, today=None):
    """Запоминает сведения о работодателе hh. Рейтинга на странице нет (скачана программой) — прежний остаётся."""
    if not info:
        return
    data = load(profile)
    old = data["hh"].get(info["id"], {})
    new = {**old, "name": name, "date": (today or date.today()).isoformat()}
    if info["category"]:
        new["category"] = info["category"]
    if info.get("site"):
        new["site"] = info["site"]
    if info.get("it") is not None:
        new["it"] = info["it"]
    if info["rating"] is not None or info["reviews"] is not None:
        new.update(rating=info["rating"], reviews=info["reviews"], rating_date=new["date"])
    data["hh"][info["id"]] = new
    save(profile, data)


def employer_id(info):
    """Номер работодателя hh из шапки вакансии (read_vacancy)."""
    m = re.search(r"/employer/(\d+)", info.get("employer", ""))
    return m.group(1) if m else None


# --- агентство или работодатель

def agency(data, company, text="", employer=None):
    """(агентство ли, почему так решили). Почему: mark — ваша пометка, hh, name — по названию, text — по описанию."""
    key = contacts.company_key(company)
    if key in data["agency"]:
        return data["agency"][key], "mark", ""
    cat = data["hh"].get(employer or "", {}).get("category")
    if cat in HH_AGENCY:
        return True, "hh", HH_AGENCY[cat]
    if m := AGENCY_NAME.search(company or ""):
        return True, "name", m.group(0)
    body = (text or "").split("\n---\n", 1)[-1]           # описание, без шапки
    if m := AGENCY_TEXT.search(body):
        return True, "text", m.group(0).strip()
    return False, "", ""


def set_mark(profile, company, value):
    """Ваша пометка «агентство / не агентство» — для всех вакансий компании; None — снять пометку."""
    key = contacts.company_key(company)
    if not key:
        return
    data = load(profile)
    if value is None:
        data["agency"].pop(key, None)
    else:
        data["agency"][key] = bool(value)
    save(profile, data)


# --- блок «О компании» в карточке

def about(profile, n, data=None):
    """Для карточки: агентство, рейтинг hh, прошлые вакансии в этой компании [{n, exact}]."""
    files = numbered_files(profile.vacancies)
    text, info = read_vacancy(files[n])
    data = data or load(profile)
    company = info.get("company", "")
    emp = employer_id(info)
    is_agency, why, what = agency(data, company, text, emp)
    hh = data["hh"].get(emp) if emp else None
    past, syn = [], contacts.synonyms(profile)
    for m, path in sorted(files.items()):
        if m == n:
            continue
        level = contacts.match_level(company, read_vacancy(path)[1].get("company", ""), syn)
        if level:
            past.append({"n": m, "exact": level == 2})
    key = contacts.company_key(company)
    return {"anonymous": not key or bool(re.search(r"anonim|neukazan", key)),       # работодатель скрыт
            "agency": is_agency, "agency_why": why, "agency_what": what, "marked": why == "mark",
            "hh": {"url": f"https://hh.ru/employer/{emp}", **({k: hh.get(k) for k in ("rating", "reviews", "rating_date", "category", "site", "it")} if hh else {})}
            if emp else None,
            "past": past}


def from_page(profile, path, page, get=None, log=None):
    """Страница hh вакансии: сведения о работодателе — в компании.json, ссылка на работодателя — в шапку вакансии,
    если её там ещё нет. get — скачивание с проверками: тогда и рейтинг со страницы работодателя (поиск на hh включён).
    True — работодатель на странице нашёлся."""
    info = hh_employer(page)
    if not info:
        return False
    text, v = read_vacancy(path)
    remember_hh(profile, info, v["company"])
    if not employer_id(v) and "**Ссылка:**" in text:
        write_text(path, text.replace("**Ссылка:**", header_line(info).rstrip("\n") + "\n**Ссылка:**", 1))
    if get:
        fetch_rating(profile, info["id"], get, log or (lambda *_: None))
    return True


# --- раздел «Компании»

def companies(profile, rows):
    """Список компаний по вакансиям профиля — строки таблицы (vacancy_rows) склеены по ключу компании.
    [{name, names, agency, agency_why, agency_what, marked, site, hh: {url, rating, reviews, rating_date, it}, finance, vacancies: [n]}];
    вакансии со скрытым работодателем — отдельно: {"items": […], "anonymous": [n]}."""
    from .sites import finance_link                       # sites импортирует company
    data = load(profile)
    files = numbered_files(profile.vacancies)
    groups, anonymous = {}, []
    for r in rows:
        key = contacts.company_key(r["company"])
        if not key or re.search(r"anonim|neukazan", key):
            anonymous.append(r["n"])
            continue
        groups.setdefault(key, []).append(r)
    items = []
    for key, rs in groups.items():
        rs.sort(key=lambda r: r["n"], reverse=True)          # свежие вакансии — первыми
        texts = [read_vacancy(files[r["n"]]) for r in rs if r["n"] in files]
        emp = next((e for e in (employer_id(info) for _, info in texts) if e), None)
        hh = data["hh"].get(emp, {}) if emp else {}
        marked = key in data["agency"]
        why = next((r for r in rs if r["agency"]), rs[0]) if not marked else rs[0]
        finance = [finance_link(r["company"], text) for r, (text, _) in zip(rs, texts)]
        site = hh.get("site") or next((re.match(r"https?://[^/]+", r["link"]).group(0) for r in rs
                                       if r["source"].startswith("Сайт ") and re.match(r"https?://", r["link"])), None)
        names = list(dict.fromkeys(r["company"] for r in rs))
        items.append({"name": names[0], "names": names, "n": rs[0]["n"],
                      "agency": why["agency"], "agency_why": why["agency_why"], "agency_what": why["agency_what"],
                      "marked": marked, "site": site,
                      "hh": {"url": f"https://hh.ru/employer/{emp}", **{k: hh.get(k) for k in ("rating", "reviews", "rating_date", "it")}}
                      if emp else None,
                      "finance": next((f for f in finance if f and f["by_inn"]), next((f for f in finance if f), None)),
                      "vacancies": [r["n"] for r in rs]})
    items.sort(key=lambda c: c["name"].lower())
    return {"items": items, "anonymous": sorted(anonymous)}
