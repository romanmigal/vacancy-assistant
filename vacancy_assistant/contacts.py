"""Трекер контактов: знакомые, через которых можно подать резюме, и кандидаты в референсеры для вакансии.

Контакты — в папке профиля (контакты.json), только на этом компьютере. Откуда берутся:
- выгрузка LinkedIn: «Настройки → Конфиденциальность данных → Получить копию данных» — большой архив
  («Download larger data archive, including connections»): из .zip берётся только Connections.csv
  (можно загрузить и сам файл); повторная загрузка обновляет компании и должности, не создавая дублей.
  LinkedIn присылает два письма: сначала базовый архив (Basic_…, без контактов), примерно через сутки — полный
  (Complete_…, с Connections.csv). Нужен полный; на базовый — понятная подсказка;
- вручную — в окне «Контакты» или из карточки вакансии.
Кандидатов в референсеры программа находит сама: сравнивает компанию вакансии с компаниями контактов —
без «ПАО», «ООО», кавычек и с учётом записи латиницей (МТС = MTS, Сбербанк = Sberbank). Модель не нужна.
Названия, которые правилами не свести («Дойче Банк» = «Deutsche Bank»), человек сам отмечает одной компанией —
синонимы профиля (синонимы_компаний.json); «это разные» тоже запоминается, чтобы не показывать пару как похожую.
"""
import csv
import io
import re
import uuid
import zipfile
from datetime import date

from . import legal
from .errors import AssistantError
from .textio import read_json, write_json

FILE = "контакты.json"
SYN_FILE = "синонимы_компаний.json"    # {"группы": [["Дойче Банк", "Deutsche Bank"], …], "разные": [["МТС Банк", "MTS"], …]}
BASIC_FILES = ("profile.csv", "skills.csv", "recommendations_received.csv", "invitations.csv", "registration.csv")   # базовая выгрузка
STATUSES = [("", "—"), ("wrote", "написал"), ("answered", "ответил"), ("talked", "поговорили"), ("referred", "передал резюме")]
FIELDS = ("name", "company", "position", "url", "email", "status", "note")

LEGAL = (r"\b(" + "|".join(f.lower() for f in legal.FORMS) +       # формы и общие слова — не часть имени
         r"|холдинг|plc|gmbh|corp|corporation|company|group|груп+а)\b")
# Одна компания под разными именами (ключи — после translit и без пробелов)
ALIASES = {"sberbank": "sber", "sberteh": "sber", "sberbankrossii": "sber", "tinkoff": "tbank", "tinkoffbank": "tbank",
           "vtbbank": "vtb", "alfabank": "alfa", "mobiletelesystems": "mts", "mobilnyetelesistemy": "mts",
           "ozonteh": "ozon", "vkontakte": "vk", "mailru": "vk", "mailrugroup": "vk",
           "sberbanktekhnology": "sber", "sberbanktehnologii": "sber",
           "doykhebank": "deutskhebank", "doykhebanktehnologii": "deutskhebank",
           "deutskhebanktekhnologykentre": "deutskhebank",
           "moskovskayabirzha": "moskovexkhange", "mosbirzha": "moskovexkhange", "moex": "moskovexkhange",
           "rayffayzenbank": "raiffeisenbank", "raiffeisenbankrussia": "raiffeisenbank",
           "bnppariba": "bnpparibas", "bnpparibaskib": "bnpparibas",
           "kitfinanke": "kitfinans", "lyuxoft": "luxoft", "vtbkapital": "vtb"}
ALIASES = {k.replace("kh", "h"): v.replace("kh", "h") for k, v in ALIASES.items()}   # «kh» и «h» — одно (см. latin)
# Общие слова названий (латиницей, по началу слова): по ним компании не сравниваются — иначе любой
# «Банк X» похож на любой «Банк Y», а «VTB Capital» — на «Альфа Капитал»
GENERIC = ("bank", "akb", "kapital", "finan", "tehnolog", "teh", "digit", "tsifrov", "servi",
           "sistem", "system", "reshen", "solution", "holding", "kompani", "rossi", "russia", "invest")
LEADING = {"bank", "akb", "kb"}       # в начале названия — описание, а не имя: «Банк ВТБ» = «ВТБ»
TRANSLIT = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
                    ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r", "s", "t",
                     "u", "f", "h", "ts", "ch", "sh", "sch", "", "y", "", "e", "yu", "ya"]))


def latin(s):
    """Строчными латинскими буквами, с выравниванием написания: «Яндекс» и «Yandex», «Кредит» и «Credit»."""
    s = "".join(TRANSLIT.get(ch, ch) for ch in s.lower().replace("ё", "е"))
    # «ch» после «c → k» — «kh», а кириллическая «х» — «h»: «Технологии» и «Technology» — одно
    for a, b in (("ks", "x"), ("ph", "f"), ("w", "v"), ("ck", "k"), ("c", "k"), ("kh", "h")):
        s = s.replace(a, b)
    return s


def company_key(name):
    """Ключ для сравнения компаний: «ПАО "МТС"» → «mts», «Т-Банк» → «tbank», «Sberbank» → «sber»,
    «Банк ВТБ (ПАО)» → «vtb»."""
    s = (name or "").lower().replace("ё", "е")
    s = re.split(r"\s*[(,;|]", s)[0]                                   # без пояснений в скобках
    tokens = re.findall(r"[a-z0-9]+", latin(re.sub(LEGAL, " ", s)))
    while len(tokens) > 1 and tokens[0] in LEADING:
        tokens = tokens[1:]
    s = "".join(tokens)
    return ALIASES.get(s, s)


# Не компании: с вакансиями не сравниваем («Self-employed» в LinkedIn — у многих)
JUNK = {company_key(x) for x in ("Self-employed", "Self employed", "Freelance", "Freelancer", "Фриланс", "Фрилансер",
                                 "Индивидуальный предприниматель", "Самозанятый", "Retired", "Пенсионер", "Stealth",
                                 "Stealth Startup", "Stealth Mode", "Unemployed", "Безработный", "Open to work",
                                 "Career break", "Sabbatical", "Confidential", "Конфиденциально")}


class Synonyms:
    """Синонимы компаний профиля: группы названий одной компании и пары «это разные компании»."""

    def __init__(self, groups=(), apart=()):
        self.groups = [list(g) for g in groups]
        self.apart = [list(p) for p in apart]
        self.map = {}
        for g in self.groups:
            keys = [k for k in (company_key(n) for n in g) if k]
            for k in keys:
                self.map[k] = keys[0]
        self.apart_keys = {frozenset((self.key(a), self.key(b))) for a, b in self.apart}

    def key(self, name):
        k = company_key(name)
        return self.map.get(k, k)

    def data(self):
        return {"группы": self.groups, "разные": self.apart}


def _clean_names(names):
    out = []
    for n in names if isinstance(names, list) else []:
        n = re.sub(r"\s+", " ", str(n)).strip()[:80]
        if n and company_key(n) and all(company_key(x) != company_key(n) for x in out):
            out.append(n)
    return out


def synonyms(profile):
    data = read_json(profile.dir / SYN_FILE, {}) if (profile.dir / SYN_FILE).exists() else {}
    data = data if isinstance(data, dict) else {}
    groups = [g for g in (_clean_names(g) for g in data.get("группы") or []) if len(g) >= 2]
    apart = [p for p in (_clean_names(p) for p in data.get("разные") or []) if len(p) == 2]
    return Synonyms(groups, apart)


def save_synonyms(profile, groups, apart):
    """Сохраняет синонимы целиком: группы с общим названием сливаются, пары из одной группы — не «разные»."""
    merged = []
    for g in (_clean_names(g) for g in groups or []):
        keys = {company_key(n) for n in g}
        joined = [m for m in merged if keys & {company_key(n) for n in m}]
        for m in joined:
            merged.remove(m)
            g = _clean_names(m + g)
        merged.append(g)
    merged = [g for g in merged if len(g) >= 2]
    syn = Synonyms(merged)
    apart = [p for p in (_clean_names(p) for p in apart or []) if len(p) == 2 and syn.key(p[0]) != syn.key(p[1])]
    syn = Synonyms(merged, apart)
    write_json(profile.dir / SYN_FILE, syn.data())
    return syn


def mark_same(profile, a, b):
    """«Это одна компания»: оба названия — в одну группу (с прежними синонимами каждого)."""
    syn = synonyms(profile)
    if not company_key(a) or not company_key(b):
        raise AssistantError("Укажите оба названия компании.")
    pair = {syn.key(a), syn.key(b)}
    return save_synonyms(profile, syn.groups + [[a, b]],
                         [p for p in syn.apart if {syn.key(p[0]), syn.key(p[1])} != pair])


def mark_apart(profile, a, b):
    """«Это разные компании»: пара больше не считается похожей."""
    syn = synonyms(profile)
    if syn.key(a) == syn.key(b):
        raise AssistantError("Эти названия отмечены одной компанией — сначала разъедините их в «Синонимах компаний».")
    return save_synonyms(profile, syn.groups, syn.apart + [[a, b]])


def words(name):
    """Значимые слова названия (латиницей) — для неточного совпадения: «МТС Банк» ~ «MTS».
    Общие слова («банк», «капитал», «технологии»…) не считаются."""
    s = re.split(r"\s*[(,;|]", (name or "").lower().replace("ё", "е"))[0]        # без пояснений: «МТС», Работа в IT
    s = latin(re.sub(LEGAL, " ", s))
    return {w for w in re.findall(r"[a-z0-9]{3,}", s) if not w.startswith(GENERIC) and w not in ("and", "the")}


def load(profile):
    return read_json(profile.dir / FILE, [])


def save(profile, items):
    write_json(profile.dir / FILE, items)


def public(items, rows=None, syn=None):
    """Контакты для окна; rows — вакансии: у каждого контакта — номера вакансий в его компании."""
    out = []
    for c in sorted(items, key=lambda c: (c.get("company", "").lower(), c.get("name", "").lower())):
        item = {k: c.get(k, "") for k in ("id", "source", "added", "status_date", *FIELDS)}
        if rows is not None:
            levels = [(r["n"], match_level(r.get("company", ""), c.get("company", ""), syn)) for r in rows]
            item["vacancies"] = [{"n": n, "exact": lvl == 2} for n, lvl in levels if lvl]
        out.append(item)
    return out


def match_level(vacancy_company, contact_company, syn=None):
    """2 — та же компания, 1 — похожее название (одно слово общее), 0 — нет. syn — синонимы профиля."""
    key = syn.key if syn else company_key
    a, b = key(vacancy_company), key(contact_company)
    if not a or not b or re.search(r"anonim|neukazan", a) or company_key(vacancy_company) in JUNK or company_key(contact_company) in JUNK:
        return 0
    if a == b:
        return 2
    if syn and frozenset((a, b)) in syn.apart_keys:                      # человек отметил: разные компании
        return 0
    # всё название одной компании входит в другую (слово — начало слова): «Сбер. IT» ~ «Sberbank», «МТС Банк» ~ «MTS»,
    # «ВТБ Факторинг» ~ «ВТБ» — или общих слов два и больше: «Филип Моррис Интернэшнл» ~ «Philip Morris Sales».
    # Одного общего слова из нескольких мало: «Smart move» и «Смарт-Тел» — разные компании
    wa, wb = words(vacancy_company), words(contact_company)
    small, big = (wa, wb) if len(wa) <= len(wb) else (wb, wa)
    common = sum(1 for x in small if any(x.startswith(y) or y.startswith(x) for y in big))
    near = bool(small) and common >= min(len(small), 2)
    return 1 if near and (a.startswith(b) or b.startswith(a) or a[:4] == b[:4]) else 0


def candidates(profile, company, limit=8):
    """Кандидаты в референсеры для компании вакансии: сначала точные совпадения, потом похожие."""
    syn = synonyms(profile)
    found = [(match_level(company, c.get("company", ""), syn), c) for c in load(profile)]
    found = [(lvl, c) for lvl, c in found if lvl]
    found.sort(key=lambda x: (-x[0], x[1].get("status", "") == "", x[1].get("name", "")))
    return [{**{k: c.get(k, "") for k in ("id", "name", "company", "position", "url", "status")}, "exact": lvl == 2}
            for lvl, c in found[:limit]]


def referrer_text(c):
    """Как референсер записывается в вакансию: «Иван Петров, CFO, МТС»."""
    return ", ".join(x for x in (c.get("name"), c.get("position"), c.get("company")) if x)


def brief(c):
    """Для таблицы: коротко — имя и должность; в подсказке — всё остальное о контакте."""
    status = dict(STATUSES).get(c.get("status", ""), "")
    lines = [referrer_text(c), f"статус: {status}" if c.get("status") else "", c.get("email"), c.get("url"), c.get("note")]
    return {"id": c["id"], "short": ", ".join(x for x in (c.get("name"), c.get("position")) if x),
            "details": "\n".join(x for x in lines if x)}


def upsert(profile, contact):
    """Добавляет контакт (без id) или правит существующий. Возвращает его id."""
    name = (contact.get("name") or "").strip()
    if not name:
        raise AssistantError("Укажите имя контакта.")
    items = load(profile)
    clean = {k: " ".join(str(contact.get(k) or "").split()) for k in FIELDS}
    if contact.get("id"):
        item = next((c for c in items if c["id"] == contact["id"]), None)
        if item is None:
            raise AssistantError("Такого контакта уже нет — обновите окно.")
        if clean["status"] != item.get("status", ""):
            item["status_date"] = date.today().isoformat() if clean["status"] else ""   # когда написал, ответил…
        item.update(clean)
    else:
        item = {"id": uuid.uuid4().hex[:12], "source": "manual", "added": date.today().isoformat(), **clean,
                "status_date": date.today().isoformat() if clean["status"] else ""}
        items.append(item)
    save(profile, items)
    return item["id"]


def delete(profile, contact_id):
    save(profile, [c for c in load(profile) if c["id"] != contact_id])


def read_linkedin(data, filename=""):
    """Строки Connections.csv из выгрузки LinkedIn (архив .zip или сам .csv): [{name, company, position, url, email}]."""
    if filename.lower().endswith(".zip") or data[:2] == b"PK":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                name = next((n for n in z.namelist() if n.lower().endswith("connections.csv")), None)
                if not name:
                    files = {n.lower().rsplit("/", 1)[-1] for n in z.namelist()}
                    if filename.lower().rsplit("/", 1)[-1].startswith("basic_") or files & set(BASIC_FILES):
                        raise AssistantError("Это базовый архив LinkedIn — контактов в нём нет. Полный архив (Complete_…) "
                                             "LinkedIn пришлёт вторым письмом, обычно через сутки после первого. Загрузите его.")
                    raise AssistantError("Это не выгрузка LinkedIn с контактами: в архиве нет файла Connections.csv.")
                data = z.read(name)
        except zipfile.BadZipFile as e:
            raise AssistantError("Архив не читается — скачайте выгрузку LinkedIn ещё раз.") from e
    text = data.decode("utf-8-sig", errors="replace")
    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines) if l.startswith("First Name")), None)   # сверху — «Notes:…»
    if start is None:
        raise AssistantError("Это не файл контактов LinkedIn: нет строки с заголовками First Name, Last Name, Company…")
    out = []
    for row in csv.DictReader(lines[start:]):
        name = " ".join(x for x in ((row.get("First Name") or "").strip(), (row.get("Last Name") or "").strip()) if x)
        if name:
            out.append({"name": name, "company": (row.get("Company") or "").strip(),
                        "position": (row.get("Position") or "").strip(), "url": (row.get("URL") or "").strip(),
                        "email": (row.get("Email Address") or "").strip()})
    return out


def name_key(name):
    """Имя для сравнения: латиницей, без порядка слов и с выровненным написанием —
    «Алексей Помазной» = «Pomaznoy Aleksei», «Юлия» = «Yulia», «Сергей» = «Sergei»."""
    out = []
    for w in re.findall(r"\w+", latin(name or "")):
        for a, b in (("shch", "sch"), ("kh", "h"), ("tz", "ts"), ("yu", "iu"), ("ya", "ia"), ("yo", "io"), ("ye", "e")):
            w = w.replace(a, b)
        w = re.sub(r"(ey|ei|iy|ii|yi|y)$", "i", w)
        out.append(re.sub(r"i+", "i", w))
    return " ".join(sorted(out))


def import_linkedin(profile, data, filename=""):
    """Загружает контакты LinkedIn. Тот же человек узнаётся по ссылке на профиль, иначе — по имени
    (кириллица и латиница, порядок слов не важен). Новые — добавляются. У найденных:
    - компания и должность берутся из LinkedIn (там их обновляет сам человек); прежнее значение,
      если оно было другим, дописывается в заметку — «раньше: …», чтобы ничего не потерялось;
    - ссылка на профиль и почта заполняются, если были пустыми;
    - имя, статус, заметка — остаются как есть.
    Возвращает счётчики: прочитано, добавлено, обновлено, с расхождениями (прежнее — в заметке)."""
    rows = read_linkedin(data, filename)
    items = load(profile)
    by_url = {c.get("url"): c for c in items if c.get("url")}
    by_name = {name_key(c.get("name")): c for c in items}
    added = updated = conflicts = 0
    for r in rows:
        item = (by_url.get(r["url"]) if r["url"] else None) or by_name.get(name_key(r["name"]))
        if not item:
            item = {"id": uuid.uuid4().hex[:12], "source": "linkedin", "added": date.today().isoformat(),
                    **{k: "" for k in FIELDS}, **r}
            items.append(item)
            by_name[name_key(r["name"])] = item
            added += 1
            continue
        changed, old = False, []
        for k, label in (("company", "компания"), ("position", "должность")):
            if r[k] and item.get(k) != r[k]:
                if item.get(k) and item.get("source") != "linkedin":       # своё значение — в заметку
                    old.append(f"{label} {item[k]}")
                item[k], changed = r[k], True
        for k in ("url", "email"):
            if r[k] and not item.get(k):
                item[k], changed = r[k], True
        if old:
            item["note"] = " · ".join(x for x in (item.get("note"), f"раньше: {', '.join(old)}") if x)
            conflicts += 1
        updated += changed
    save(profile, items)
    return {"read": len(rows), "added": added, "updated": updated, "conflicts": conflicts, "total": len(items)}
