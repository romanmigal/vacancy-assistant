"""Свои отправленные письма — образцы стиля для нового письма.

Шаблон письма неизменный, а настоящий стиль человека — в письмах, которые он сам поправил или написал
и отправил (source edit/own и отметка «Отправлено» в паспорте письма). Два последних таких письма к похожей
роли (CIO, CTO… — similar.roles, затем общие слова названия) идут в промпт рядом с шаблоном: из них — стиль,
факты — только из резюме и вакансии. Выключатель — в «Шаблонах писем».

Ещё — письмо, уже отправленное в ту же компанию (любое, и версия модели): модель его видит, чтобы не повторить
слово в слово, если откликаетесь в компанию или агентство второй раз.
"""
import json
import re

from . import letter_frame
from .profile import plain_title
from .textio import read_text

SETTING = "учитывать_отправленные"      # профиль.json → «письмо»
COUNT = 2                               # сколько писем в промпт
MAX_CHARS = 1500                        # письмо длиннее — не образец: раздувает промпт
HISTORY = "история"                     # как analysis.HISTORY: импорт оттуда — круговой
SOURCES = ("edit", "own")               # как analysis.SOURCES
HEAD = re.compile(r"^# Письмо: (.+)$", re.M)
ANONYMOUS = re.compile(r"аноним|конфиденциальн|не указан", re.I)
WORD = re.compile(r"[а-яёa-z]{3,}", re.I)


def enabled(profile):
    """По умолчанию включено: пока своих отправленных писем нет, ничего не меняется."""
    return bool(profile.config["письмо"].get(SETTING, True))


def set_enabled(profile, on):
    profile.config["письмо"][SETTING] = bool(on)
    profile.save_config()


def _read(path):
    """(паспорт, название вакансии, компания, текст письма) файла письма."""
    text = read_text(path)
    m = re.match(r"<!-- (\{.*\}) -->", text)
    head = HEAD.search(text)
    title, _, company = (head.group(1) if head else "").rpartition(" — ")
    body = text.split("\n---\n", 1)[1] if "\n---\n" in text else ""
    return (json.loads(m.group(1)) if m else {}), title, company, body.strip()


def _sent_letters(profile, own=True):
    """Отправленные письма: [{name, title, company, sent, text}] — по одному на вакансию (последнее отправленное),
    новые сверху. own — только свои и поправленные. text — середина письма, без приветствия, готовности,
    завершения и подписи."""
    folder, found = profile.letters, {}
    if not folder.exists():
        return []
    files = list(folder.glob("*.md")) + (list((folder / HISTORY).glob("*/*.md")) if (folder / HISTORY).exists() else [])
    for f in files:
        name = f.name if f.parent == folder else f.parent.name + ".md"
        meta, title, company, body = _read(f)
        if (own and meta.get("source") not in SOURCES) or not meta.get("sent") or not body:
            continue
        stamp = f"{meta['sent']} {meta.get('sent_time', '')}"
        if name not in found or stamp > found[name]["stamp"]:
            middle = letter_frame.strip_frame(body, profile)
            if middle and len(middle) <= MAX_CHARS:
                found[name] = {"name": name, "title": title, "company": company, "sent": meta["sent"],
                               "stamp": stamp, "text": middle}
    return sorted(found.values(), key=lambda x: x["stamp"], reverse=True)


def sent(profile):
    """Свои отправленные письма (правка или своё) — образцы стиля."""
    return _sent_letters(profile)


def earlier(profile, name, company):
    """Последнее письмо, уже отправленное в эту компанию к другой вакансии (любое — и версия модели), или ""."""
    from .contacts import company_key
    key = company_key(company)
    if not key or ANONYMOUS.search(company or ""):
        return ""
    return next((x["text"] for x in _sent_letters(profile, own=False)
                 if x["name"] != name and company_key(x["company"]) == key), "")


def _words(title):
    return {w[:5] for w in WORD.findall(plain_title(title).lower().replace("ё", "е"))}


def pick(profile, name, title, count=COUNT):
    """Образцы для письма к вакансии name с названием title: письма к той же роли и с общими словами названия
    выше, при равенстве — новее. Письма к этой же вакансии — не образец. [текст]."""
    if not enabled(profile):
        return []
    from .similar import roles                              # similar → market → … — только когда нужно
    role, words = roles(title), _words(title)
    items = [x for x in sent(profile) if x["name"] != name]
    items.sort(key=lambda x: (bool(role & roles(x["title"])), len(words & _words(x["title"]))), reverse=True)
    return [x["text"] for x in items[:count]]          # sort устойчивый: при равенстве остаются новые сверху


def block(samples):
    """Образцы для промпта ({samples}); образцов нет — пусто, и промпт как без них."""
    if not samples:
        return ""
    letters = "\n\n".join(f"--- Письмо {i} ---\n{s}" for i, s in enumerate(samples, 1))
    return ("Мои отправленные письма — их я сам написал или поправил и отправил на похожие вакансии. "
            "Пиши в их стиле: такими же словами и так же рассказывай об опыте. Факты, компании и цифры "
            "из них не бери — только из резюме и вакансии.\n\n"
            f"=== МОИ ОТПРАВЛЕННЫЕ ПИСЬМА ===\n{letters}\n=== КОНЕЦ ОТПРАВЛЕННЫХ ПИСЕМ ===\n\n")


def earlier_block(text):
    """Письмо, уже отправленное в эту компанию, для промпта ({earlier}); нет — пусто."""
    if not text:
        return ""
    return ("В эту компанию я уже отправлял письмо к другой вакансии. Не повторяй его слово в слово: "
            "те же факты можно, но другими словами, и начни иначе.\n\n"
            f"=== ПИСЬМО, УЖЕ ОТПРАВЛЕННОЕ В ЭТУ КОМПАНИЮ ===\n{text}\n=== КОНЕЦ ПИСЬМА ===\n\n")


def requirements_block(text):
    """Требования вакансии с подтверждением из резюме для промпта ({requirements}); нет — пусто."""
    if not text:
        return ""
    return ("Требования вакансии, которые подтверждает моё резюме (из разбора), — подсказка, что важно этой вакансии. "
            "Когда выбираешь, какие результаты из резюме упомянуть, бери те, что отвечают на самые важные из этих "
            "требований, а не одни и те же для любой вакансии. Форму и длину письма это не меняет: их задают "
            "образец и мои отправленные письма, отдельных пунктов под требования не добавляй.\n\n"
            f"=== ТРЕБОВАНИЯ ВАКАНСИИ И МОЙ ОПЫТ ===\n{text}\n=== КОНЕЦ ТРЕБОВАНИЙ ===\n\n")
