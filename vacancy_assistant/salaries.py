"""Окно «Зарплаты»: вилки из вакансий профиля — медиана, квартили, разброс, доля без зарплаты; группы по уровню
должности, городу и формату; своя планка на графике. Без модели.

Это не весь рынок, а только вакансии, которые видел профиль. Зарплаты приводятся к одному виду:
    «от–до» → середина вилки, «от X» → X, «до Y» → Y; за месяц, в рублях;
    «до вычета» ↔ «на руки» — по прогрессивному НДФЛ (13/15/18/20/22 %) на годовой доход;
    валюта — по курсу ЦБ на сегодня (запрашивается раз в день; если ЦБ недоступен — без пересчёта, с пометкой).
"""
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date
from statistics import median, quantiles

from .files import numbered_files, read_vacancy
from .textio import read_json, write_json

RATES_FILE = "курсы ЦБ.json"                         # в папке профилей: {"date": "2026-10-29", "rates": {"USD": 81.5}}
RATES_URL = "https://www.cbr.ru/scripts/XML_daily.asp"
NDFL = [(2_400_000, .13), (5_000_000, .15), (20_000_000, .18), (50_000_000, .20), (float("inf"), .22)]   # годовой доход
CURRENCIES = [("USD", r"\$|USD|долл"), ("EUR", r"€|EUR|евро"), ("KZT", r"₸|KZT|тенге"),
              ("UZS", r"UZS|сум(?!м)"), ("BYN", r"BYN|Br\b|бел\.? ?руб"), ("RUB", r"₽|руб|RUR|RUB")]
MIN_GROUP = 3                                        # группа меньше — без квартилей


def parse(text):
    """«от 300 000 до 400 000 ₽ за месяц до вычета налогов» → {"low": 300000, "high": 400000, "net": False,
    "currency": "RUB"}; без чисел («не указана», «по договорённости») — None. «300–400 тыс.» тоже понимает."""
    t = (text or "").replace(" ", " ").replace(" ", " ")
    thousands = re.search(r"\d\s*(тыс|k\b|К\b)", t, re.I)
    nums = [int(re.sub(r"\D", "", n)) for n in re.findall(r"\d[\d ]*\d|\d", t)]
    nums = [n * 1000 if thousands and n < 10_000 else n for n in nums if n]
    if not nums:
        return None
    if len(nums) >= 2:
        low, high = nums[0], nums[1]
    elif re.match(r"\s*до\b", t, re.I):
        low, high = None, nums[0]
    else:
        low, high = nums[0], None
    currency = next((c for c, rx in CURRENCIES if re.search(rx, t, re.I)), "RUB")
    return {"low": low, "high": high, "net": bool(re.search(r"на руки|после вычета|net", t, re.I)), "currency": currency}


def tax(annual):
    """НДФЛ с годового дохода по прогрессивной шкале."""
    total, prev = 0, 0
    for top, rate in NDFL:
        if annual <= prev:
            break
        total += (min(annual, top) - prev) * rate
        prev = top
    return total


def to_net(gross_month):
    return gross_month - tax(gross_month * 12) / 12


def to_gross(net_month):
    """Обратный пересчёт: сколько «до вычета» даёт эту сумму на руки — по ступеням шкалы."""
    annual_net, prev, net_prev = net_month * 12, 0, 0
    for top, rate in NDFL:
        net_top = net_prev + (top - prev) * (1 - rate)
        if annual_net <= net_top:
            return (prev + (annual_net - net_prev) / (1 - rate)) / 12
        prev, net_prev = top, net_top


def point(s):
    """Одно число вилки: середина «от–до», иначе «от» или «до»."""
    if s["low"] and s["high"]:
        return (s["low"] + s["high"]) / 2
    return s["low"] or s["high"]


def fetch_rates():
    """Курсы ЦБ на сегодня: {"USD": 81.5, …} — рублей за единицу валюты."""
    with urllib.request.urlopen(RATES_URL, timeout=10) as r:
        root = ET.fromstring(r.read())
    return {v.findtext("CharCode"): float(v.findtext("Value").replace(",", ".")) / int(v.findtext("Nominal"))
            for v in root.iter("Valute")}


def rates(folder, today=None, fetch=fetch_rates):
    """Курсы из кэша, если он сегодняшний, иначе — запрос к ЦБ. Не вышло — прежний кэш с его датой или пусто.
    → ({валюта: курс}, дата курса или "", пометка для окна)."""
    today = (today or date.today()).isoformat()
    cache = read_json(folder / RATES_FILE, {})
    if cache.get("date") == today:
        return cache["rates"], today, ""
    try:
        fresh = fetch()
        write_json(folder / RATES_FILE, {"date": today, "rates": fresh})
        return fresh, today, ""
    except Exception:
        if cache.get("rates"):
            return cache["rates"], cache["date"], f"ЦБ сейчас недоступен — курс на {cache['date']}"
        return {}, "", "ЦБ недоступен — зарплаты в валюте не пересчитаны и не вошли в расчёт"


def where_format(text):
    """Город и формат из шапки вакансии («**Где:** Москва, гибрид») и строки «Формат работы:», если она есть."""
    m = re.search(r"\*\*Где:\*\*[ \t]*(.*?)[ \t]*$", text, re.M)
    where = (m.group(1) if m else "").strip(" ,")
    parts = [x.strip() for x in where.split(",") if x.strip()]
    fmt = re.search(r"Формат работы:?\**[ \t]*([^\n]+)", text)
    found = " ".join(parts[1:] + [fmt.group(1) if fmt else ""]).lower()
    city = parts[0] if parts and not parts[0].startswith("не указан") else ""
    if city.lower().startswith("удал"):
        city, found = "", found + " удалённо"
    format_ = "удалённо" if "удал" in found else "гибрид" if "гибрид" in found else "офис" if "офис" in found else ""
    return city, format_


def level(title, spec):
    """Слово уровня из фильтра по названию, которое есть в названии вакансии: «Директор», «CIO»… — или ""."""
    from .profile import W
    alts = [(p, p) for p in spec.get("части", [])] + [(W(w), w) for w in spec.get("слова", [])]
    for rx, _ in alts:
        m = re.search(rx, title, re.I)
        if m:
            word = m.group(0)
            return word[0].upper() + word[1:]
    return ""


def summary(values):
    """Медиана, квартили, разброс; квартили — от MIN_GROUP значений."""
    if not values:
        return None
    v = sorted(values)
    q = quantiles(v, n=4, method="inclusive") if len(v) >= MIN_GROUP else None
    return {"count": len(v), "median": round(median(v)), "q1": round(q[0]) if q else None, "q3": round(q[2]) if q else None,
            "min": round(v[0]), "max": round(v[-1])}


def compute(items, planka=0, rate=None, note=""):
    """items — [{"n", "title", "company", "salary", "city", "format", "level"}]; rate — {валюта: курс}.
    → итоги на руки и до вычета, группы, точки для графика, планка."""
    rate = rate or {}
    points, skipped = [], []
    for it in items:
        s = parse(it["salary"])
        if not s:
            continue
        value = point(s)
        if s["currency"] != "RUB":
            if s["currency"] not in rate:
                skipped.append(it["n"])
                continue
            value *= rate[s["currency"]]
        net, gross = (value, to_gross(value)) if s["net"] else (to_net(value), value)
        points.append({**{k: it[k] for k in ("n", "title", "company", "salary", "city", "format", "level")},
                       "net": round(net), "gross": round(gross), "currency": s["currency"], "given_net": s["net"]})

    def groups(key, empty):
        out = {}
        for p in points:
            out.setdefault(p[key] or empty, []).append(p)
        return sorted(({"label": k, "net": summary([p["net"] for p in ps]), "gross": summary([p["gross"] for p in ps])}
                       for k, ps in out.items()), key=lambda g: (-g["net"]["count"], g["label"]))

    return {"total": len(items), "with_salary": len(points), "without": len(items) - len(points) - len(skipped),
            "skipped": skipped, "note": note, "planka": planka,
            "net": summary([p["net"] for p in points]), "gross": summary([p["gross"] for p in points]),
            "above": {"net": sum(p["net"] >= planka for p in points) if planka else None,
                      "gross": sum(p["gross"] >= planka for p in points) if planka else None},
            "groups": {"level": groups("level", "другое"), "city": groups("city", "не указан"), "format": groups("format", "не указан")},
            "points": sorted(points, key=lambda p: p["net"])}


def items(profile):
    """Вакансии профиля для расчёта — все, которые он видел (и отсеянные фильтром тоже)."""
    spec = profile.config["поиск"].get("название_уровень", {})
    out = []
    for n, path in sorted(numbered_files(profile.vacancies).items()):
        text, info = read_vacancy(path)
        city, fmt = where_format(text)
        out.append({"n": n, "title": info["title"], "company": info["company"], "salary": info["salary"],
                    "city": city, "format": fmt, "level": level(info["title"], spec)})
    return out


def report(profile, folder, planka=0, fetch=fetch_rates, today=None):
    """Окно «Зарплаты»: курсы ЦБ запрашиваются, только если есть зарплаты в валюте."""
    its = items(profile)
    foreign = any((parse(i["salary"]) or {}).get("currency", "RUB") != "RUB" for i in its)
    rate, rate_date, note = rates(folder, today, fetch) if foreign else ({}, "", "")
    res = compute(its, planka, rate, note)
    used = sorted({p["currency"] for p in res["points"]} - {"RUB"})
    return {**res, "rate_date": rate_date, "rates": {c: round(rate[c], 2) for c in used}}
