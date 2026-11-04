"""Разбор ответа модели (#67) — один на всю программу: оценки и решение для таблицы, карточка вакансии,
окно «Мои оценки», сильные стороны для письма.

Формат ответа задан шаблоном разбора, но модели пишут его по-разному, особенно GigaChat:
«### Оценка: 8/10», «**Могу:** 7/10», пояснение после тире, в скобках или строками с тире ниже,
точка после «/10», «Оценка» после «Пробелов», раздел без пунктов, «Отсутствуют» обычным текстом,
«Оцена» с опечаткой. Порядок строк не важен: каждая относится к своему разделу или оценке.
Образцы всех встречавшихся вариантов — tests/fixtures/ответы/, проверка своих разборов — razbor.py check-analyses.
"""
import re

SECTIONS = ("Критерии", "Требования", "Сильные стороны", "Пробелы")
# «Хочешь», «Можете» — модель иногда обращается к человеку (GigaChat, вакансия 43); остальное — общая оценка
SCORES = {"могу": "can", "можешь": "can", "можете": "can", "хочу": "want", "хочешь": "want", "хотите": "want"}
META = {"can": "can", "want": "want", "total": "score"}   # поля паспорта разбора
ITEM = re.compile(r"^(?:\d+[.)]|[-•*—–])\s*")

_HEAD = re.compile(r"^(%s)\s*(?::\s*(.*))?$" % "|".join(SECTIONS), re.I)   # «Требования к опыту — ✅» — не заголовок
_SCORE = re.compile(r"^(Могу|Можешь|Можете|Хочу|Хочешь|Хотите|(?:Общая |Итоговая )?Оцен[а-я]*)\s*:\s*(\d+)\s*(.*)$", re.I)
_CRIT = re.compile(r"^К\s*(\d+)\s*[:.]\s*(✅|❌|❓)?\s*(.*)$")
_DECISION = re.compile(r"^Откликаться\s*:\s*(.*)$", re.I)


def _clean(raw):
    """«### **Оценка:** 8/10» → «Оценка: 8/10»: без разметки заголовков и жирного."""
    return raw.replace("**", "").strip().lstrip("#").strip()


def _why(rest):
    """Хвост строки оценки после числа: «/10 — пояснение», «/10 (пояснение).», «/10.» → «пояснение»."""
    rest = re.sub(r"^(?:/\s*10|из\s+10)?\s*\.?\s*", "", rest)
    m = re.fullmatch(r"\((.*)\)\.?", rest)
    return (m.group(1) if m else rest.lstrip("—–:- ")).strip()


def parse(text):
    """Ответ модели → структура:
    criteria [{k, mark, text}], requirements [{text, ok}], strengths [..], gaps [..],
    can / want / total — {score, why: [..]} или None, decision («да», «нет», «да, но с оговорками», «?»),
    decision_note (пояснение в скобках), sections — какие заголовки разделов были, other — строки вне разделов."""
    out = {"criteria": [], "requirements": [], "strengths": [], "gaps": [],
           "can": None, "want": None, "total": None, "decision": "?", "decision_note": "",
           "sections": [], "other": []}
    lists = {"Требования": "requirements", "Сильные стороны": "strengths", "Пробелы": "gaps"}
    section = score = None                   # куда идут строки ниже: раздел или пояснение к оценке
    for raw in (text or "").splitlines():
        line = _clean(raw)
        if not line:
            continue
        if m := _HEAD.match(line):
            name = next(s for s in SECTIONS if s.lower() == m.group(1).lower())
            section, score = name, None
            if name not in out["sections"]:
                out["sections"].append(name)
            if m.group(2):                       # «Пробелы: нет опыта в продажах; …» — текст в той же строке
                _add(out, lists.get(name), m.group(2))
            continue
        if m := _CRIT.match(line):
            out["criteria"].append({"k": m.group(1), "mark": m.group(2) or "", "text": m.group(3).strip(" —-–")})
            score = None
            continue
        if m := _SCORE.match(line):
            key = SCORES.get(m.group(1).lower(), "total")
            why = _why(m.group(3))
            out[key] = {"score": int(m.group(2)), "why": [why] if why else []}
            score = key
            continue
        if m := _DECISION.match(line):
            d = m.group(1).strip()
            dm = re.match(r"^([^(]+?)\s*(\(.*)?$", d)
            out["decision"] = (dm.group(1) if dm else d).strip(" .«»") or "?"
            out["decision_note"] = (dm.group(2) or "").strip() if dm else ""
            section = score = None
            continue
        if score and re.match(r"^[—–-]\s*\S", line):   # «Могу: 7/10» и ниже «— нет команды 50+» — к своей оценке
            out[score]["why"].append(ITEM.sub("", line))
            continue
        score = None
        if section in lists:
            _add(out, lists[section], line, item=bool(ITEM.match(line)))
        else:                                    # вне разделов или пояснение к критериям без «К…» — не теряем
            out["other"].append(line)
    return out


def _add(out, key, line, item=True):
    """Пункт раздела; строка без номера или маркера после пункта — его продолжение."""
    if not key:
        return
    text = ITEM.sub("", line).strip()
    items = out[key]
    if not item and items and not re.match(r"^(?:отсутству|нет\b)", text, re.I) and text[:1].islower():
        prev = items[-1]
        if key == "requirements":
            prev["text"] += " " + text
            prev["ok"] = "❌" not in prev["text"]
        else:
            items[-1] = prev + " " + text
        return
    items.append({"text": text, "ok": "❌" not in text} if key == "requirements" else text)


def result(text):
    """Оценки и решение — для паспорта разбора и таблицы: {score, can, want, decision}."""
    p = parse(text)
    num = lambda key: p[key]["score"] if p[key] else None
    return {"score": num("total"), "can": num("can"), "want": num("want"), "decision": p["decision"]}


def problems(text, meta=None):
    """Что в разборе не так — для razbor.py check-analyses: нет оценки, числа не совпадают с паспортом,
    пустой раздел, строки, которые никуда не отнесены."""
    p, out = parse(text), []
    short = (meta or {}).get("stage") == "short"
    for key, name in (("can", "Могу"), ("want", "Хочу"), ("total", "Оценка")):
        if not p[key]:
            out.append(f"нет оценки «{name}»")
        elif meta is not None and meta.get(META[key]) != p[key]["score"]:
            out.append(f"«{name}» {p[key]['score']} в тексте, {meta.get(META[key]) if meta.get(META[key]) is not None else 'нет'} в таблице")
    if p["decision"] == "?":
        out.append("нет решения «Откликаться»")
    if not p["criteria"]:
        out.append("нет отметок критериев")
    for name in SECTIONS[1:]:
        key = {"Требования": "requirements", "Сильные стороны": "strengths", "Пробелы": "gaps"}[name]
        if name in p["sections"] and not p[key]:
            out.append(f"раздел «{name}» пустой")
        elif not short and name not in p["sections"]:
            out.append(f"нет раздела «{name}»")
    if p["other"]:
        out.append("строки вне разделов: " + " | ".join(s[:60] for s in p["other"][:3]))
    return out


def check_profile(profile):
    """Разборы профиля с замечаниями: [(имя файла, [замечания])]. Только чтение."""
    from .files import analysis_body, numbered_files, read_meta     # files сам импортирует этот модуль
    from .textio import read_text
    out = []
    for _, path in sorted(numbered_files(profile.results).items()):
        meta = read_meta(path)
        if not meta or meta.get("stage") in (None, "", "none"):     # не разобрана или «Без модели»
            continue
        if found := problems(analysis_body(read_text(path)), meta):
            out.append((path.name, found))
    return out
