"""«Хочу» выше у вакансий, похожих на свежие отклики.

Самый честный сигнал интереса — вакансии, на которые человек откликнулся сам. Образцы — последние RECENT
откликов не старше DAYS дней (любой этап, и «Отказ»: отказ работодателя не значит, что вакансия была неинтересна).
Похожая — та же роль в названии (CIO, CTO, CDO…) и близкий текст: косинус TF-IDF по словам описаний всех
вакансий профиля, чтобы общие для всех слова («команда», «ИТ», «бюджет») не весили. Без модели и детерминированно.
Надбавка считается при сборке списка: отметили отклик — похожие поднимаются сразу. «Хочу» модели в разборе
не меняется — надбавка отдельным полем.
"""
import collections
import math
import re
from datetime import date, timedelta

from . import market
from .profile import plain_title

RECENT = 10            # сколько последних откликов брать образцами
DAYS = 90              # отклики старше — не образцы: вкус успевает сдвинуться
MIN_SAMPLES = 3        # меньше — надбавки нет: двух откликов мало, чтобы говорить о вкусе
THRESHOLD = 0.15       # косинус TF-IDF, с которого вакансии похожи (подобран на вакансиях профиля)
MANY = 3               # похожа на столько откликов и больше — +2, иначе +1

# Роль по названию: похожими считаем только вакансии одной роли
ROLES = {
    "cio": r"\bcio\b|(?:ит|it)[- ]?директор|директор\w*\s+(?:по\s+)?(?:ит|it)\b(?!-?компан)|директор\w* по информационным технологиям|"
           r"it[- ]director|head of it\b|руководител\w*\s+(?:ит|it)\b|(?:ит|it)[- ]?департамент\w*|"
           r"департамент\w* информационных технологий|chief information officer",
    "cto": r"\bcto\b|технически\w*\s+директор\w*|chief technology officer|head of engineering|vp of engineering|"
           r"директор\w* по разработке",
    "cdo": r"\bcdo\b|chief digital|цифров\w*\s+трансформац\w*|директор\w* по цифров\w*",
    "ciso": r"\bciso\b|информационной безопасности|директор\w* по иб\b",
    "cpo": r"\bcpo\b|chief product|директор\w* по продукт\w*",
}
NOT_ROLE = re.compile(r"chief investment|директор\w* по инвестиц", re.I)     # «CIO» бывает и инвестиционным
WORD = re.compile(r"[а-я]{4,}|[a-z]{2,}")
SETTING = "похожие_на_отклики"


def roles(title):
    t = plain_title(title).lower().replace("ё", "е")
    if NOT_ROLE.search(t):
        return set()
    return {k for k, rx in ROLES.items() if re.search(rx, t)}


def words(text):
    """Слова описания по первым 6 буквам — без общих слов требований и английских служебных."""
    t = market._body(text).lower().replace("ё", "е")
    return collections.Counter(w[:6] for w in WORD.findall(t) if w[:5] not in market.COMMON and w not in market.STOP)


def vectors(texts):
    """{n: вектор TF-IDF} — слова, которые есть только в одной вакансии, не сближают ни с чем и не считаются."""
    counts = {n: words(t) for n, t in texts.items()}
    df = collections.Counter(w for c in counts.values() for w in c)
    total = len(counts)
    out = {}
    for n, c in counts.items():
        v = {w: (1 + math.log(k)) * math.log(total / df[w]) for w, k in c.items() if df[w] > 1}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1
        out[n] = {w: x / norm for w, x in v.items()}
    return out


def cosine(a, b):
    if len(a) > len(b):
        a, b = b, a
    return sum(x * b.get(w, 0) for w, x in a.items())


def applied_on(r):
    """Когда откликнулись: первый этап в истории (или дата этапа)."""
    f = r.get("funnel") or {}
    if not f.get("stage"):
        return ""
    return min([h["date"] for h in f.get("history", []) if h.get("date")] or [f.get("date") or ""])


def samples(rows, today=None):
    """Образцы — последние RECENT откликов не старше DAYS дней; меньше MIN_SAMPLES — пусто."""
    since = ((today or date.today()) - timedelta(days=DAYS)).isoformat()
    got = sorted((r for r in rows if applied_on(r) >= since), key=lambda r: (applied_on(r), r["n"]), reverse=True)[:RECENT]
    return got if len(got) >= MIN_SAMPLES else []


def _same(a, b):
    """Та же вакансия ещё раз (дубль): одно название у одной компании."""
    key = lambda r: (re.sub(r"\W+", "", r["title"].lower()), re.sub(r"\W+", "", r["company"].lower()))
    return key(a) == key(b)


def bonuses(rows, texts, today=None):
    """{n: {"bonus": 1 или 2, "like": [{n, title, company, date}]}} — для разобранных вакансий без отклика,
    похожих на свежие отклики. texts — {n: текст файла вакансии}."""
    base = samples(rows, today)
    if not base:
        return {}
    vec = vectors(texts)
    role = {r["n"]: roles(r["title"]) for r in rows}
    out = {}
    for r in rows:
        if r["want"] is None or applied_on(r) or r["n"] not in vec:
            continue
        like = [s for s in base if role[r["n"]] & role[s["n"]] and s["n"] in vec and not _same(r, s)
                and cosine(vec[r["n"]], vec[s["n"]]) >= THRESHOLD]
        if like:
            out[r["n"]] = {"bonus": 2 if len(like) >= MANY else 1,
                           "like": [{"n": s["n"], "title": s["title"], "company": s["company"], "date": applied_on(s)} for s in like]}
    return out


def enabled(profile):
    """Выключатель в Настройках; по умолчанию включено."""
    return bool((profile.config.get("оценка") or {}).get(SETTING, True))


def set_enabled(profile, on):
    profile.config["оценка"] = {**(profile.config.get("оценка") or {}), SETTING: bool(on)}
    profile.save_config()
