"""Склейка дублей (#13): одна вакансия на hh, на сайте компании и в Telegram — одна карточка.

При добавлении новую вакансию сравниваем с вакансиями профиля за последние DAYS дней: та же компания
(contacts.company_key) и похожее название (значимые слова, Жаккар ≥ TITLE_SIM). Если ещё и начало описания
похоже (TEXT_SIM) — это та же вакансия: новую карточку не создаём, ссылку дописываем в шапку прежней полем
«Ещё ссылки». Описание не похоже (сайты пишут его по-разному) — карточку создаём с пометкой «Возможно, дубль»:
решает человек — «Склеить» или «Это разные». Вакансии с одного сайта — дубль, только если совпадает и город,
и почти весь текст (SAME_SITE_SIM): работодатель на hh бывает публикует одну вакансию несколько раз подряд под
разными номерами. Та же вакансия в другом городе — отдельное объявление, не дубль.
"""
import re
import urllib.parse
from datetime import date, timedelta

from .contacts import company_key
from .files import numbered_files, read_vacancy
from .profile import plain_title
from .textio import read_text, write_text

DAYS = 60
TITLE_SIM = 0.7
TEXT_SIM = 0.5
SAME_SITE_SIM = 0.9              # с одного сайта — почти тот же текст, иначе это разные вакансии компании
HEAD = 500                       # сколько знаков начала описания сравнивать
MORE_FIELD = "Ещё ссылки"
MAYBE_FIELD = "Возможно, дубль"
STOP = set("""в во на по и или для с со к от до из за the of and for in at to a an
вакансия вакансии job position""".split())
WORD = re.compile(r"[a-zа-я0-9]+")


def _words(text, cut=None):
    t = plain_title(text).lower().replace("ё", "е") if cut is None else text.lower().replace("ё", "е")[:cut]
    return {w[:6] for w in WORD.findall(t) if w not in STOP and (len(w) > 1 or w.isdigit())}


def jaccard(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0


def _body(text):
    return text.split("\n---\n", 1)[-1].strip()


def _day(saved):
    m = re.match(r"(\d{2})\.(\d{2})\.(\d{4})", saved or "")
    return date(int(m.group(3)), int(m.group(2)), int(m.group(1))) if m else None


def _where(text):
    m = re.search(r"^\*\*Где:\*\*[ \t]*(.*?)[ \t]*$", text, re.M)
    return re.sub(r"[\s,]+", " ", m.group(1)).strip().lower() if m else ""


def _host(url):
    return urllib.parse.urlsplit(url).netloc.lower().removeprefix("www.") if re.match(r"https?://", url or "") else ""


def find(profile, title, company, text, link="", today=None, skip=None):
    """Похожая вакансия профиля с другого сайта: (номер, файл, уверены ли) или None. skip — файл, который не сравнивать."""
    key = company_key(company)
    if not key or re.search(r"anonim|neukazan", key) or not profile.vacancies.is_dir():
        return None
    since = (today or date.today()) - timedelta(days=DAYS)
    tw, head = _words(title), _words(_body(text), HEAD)
    best = None
    for n, path in sorted(numbered_files(profile.vacancies).items(), reverse=True):
        if skip and path == skip:
            continue
        old_text, old = read_vacancy(path)
        same_site = bool(_host(link)) and _host(link) == _host(old["link"])
        if same_site and _where(text) != _where(old_text):
            continue                                   # hh: та же вакансия в другом городе — отдельное объявление
        day = _day(old["saved"])
        if day and day < since or company_key(old["company"]) != key or jaccard(tw, _words(old["title"])) < TITLE_SIM:
            continue
        sure = jaccard(head, _words(_body(old_text), HEAD)) >= (SAME_SITE_SIM if same_site else TEXT_SIM)
        if same_site and not sure:
            continue                                   # с одного сайта «возможно» не ставим: разные вакансии компании
        if sure:
            return n, path, True
        best = best or (n, path, False)
    return best


def _set_field(text, name, value):
    """Поле шапки «**name:** value» — заменить или вставить перед «Сохранено»; пустое value — убрать."""
    line = re.compile(rf"^\*\*{re.escape(name)}:\*\*[^\n]*\n", re.M)
    text = line.sub("", text, count=1)
    if value:
        text = re.sub(r"^(\*\*Сохранено:\*\*)", lambda m: f"**{name}:** {value}  \n" + m.group(1), text, count=1, flags=re.M)
    return text


def more_links(text):
    m = re.search(rf"^\*\*{re.escape(MORE_FIELD)}:\*\*[ \t]*(.*?)[ \t]*$", text, re.M)
    return [u for u in re.split(r"[ ,]+", m.group(1)) if u.startswith("http")] if m else []


def add_link(path, url):
    """Дописать ссылку в «Ещё ссылки» вакансии. False — если она там уже есть или это основная ссылка."""
    text = read_text(path)
    links = more_links(text)
    if not url or url in links or url == read_vacancy(path)[1]["link"]:
        return False
    write_text(path, _set_field(text, MORE_FIELD, ", ".join(links + [url])))
    return True


def mark_maybe(text, n):
    return _set_field(text, MAYBE_FIELD, str(n))


def clear_maybe(path):
    write_text(path, _set_field(read_text(path), MAYBE_FIELD, ""))


def check(profile, title, company, text, link, log):
    """Перед сохранением новой вакансии. Уверены, что дубль, — ссылка дописана к прежней, возвращает её файл
    (новую не сохранять). Не уверены — возвращает текст с пометкой «Возможно, дубль». Иначе — текст как есть."""
    found = find(profile, title, company, text, link)
    if not found:
        return None, text
    n, path, sure = found
    if sure:
        from .sites import source
        added = add_link(path, link)
        log(f"Уже есть под номером {n:02d} ({source(read_vacancy(path)[1]['link'], company)})"
            + (", добавил ссылку" if added else "") + f": {title} — {company}")
        return path, None
    log(f"      возможно, то же, что № {n:02d} — проверьте в карточке: «Склеить» или «Это разные»")
    return None, mark_maybe(text, n)
