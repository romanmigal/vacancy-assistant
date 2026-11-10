"""Свои отправленные письма — образцы стиля для нового письма.

Шаблон письма неизменный, а настоящий стиль человека — в письмах, которые он сам поправил или написал
и отправил (source edit/own и отметка «Отправлено» в паспорте письма). Два последних таких письма к похожей
роли (CIO, CTO… — similar.roles, затем общие слова названия) идут в промпт рядом с шаблоном: из них — стиль,
факты — только из резюме и вакансии. Выключатель — в «Шаблонах писем».
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
HEAD = re.compile(r"^# Письмо: (.+?) — [^\n]*$", re.M)
WORD = re.compile(r"[а-яёa-z]{3,}", re.I)


def enabled(profile):
    """По умолчанию включено: пока своих отправленных писем нет, ничего не меняется."""
    return bool(profile.config["письмо"].get(SETTING, True))


def set_enabled(profile, on):
    profile.config["письмо"][SETTING] = bool(on)
    profile.save_config()


def _read(path):
    """(паспорт, название вакансии, текст письма) файла письма."""
    text = read_text(path)
    m = re.match(r"<!-- (\{.*\}) -->", text)
    head = HEAD.search(text)
    body = text.split("\n---\n", 1)[1] if "\n---\n" in text else ""
    return (json.loads(m.group(1)) if m else {}), (head.group(1) if head else ""), body.strip()


def sent(profile):
    """Свои отправленные письма: [{name, title, sent, text}] — по одному на вакансию, новые сверху.
    text — середина письма, без приветствия, готовности, завершения и подписи."""
    folder, found = profile.letters, {}
    if not folder.exists():
        return []
    files = list(folder.glob("*.md")) + (list((folder / HISTORY).glob("*/*.md")) if (folder / HISTORY).exists() else [])
    for f in files:
        name = f.name if f.parent == folder else f.parent.name + ".md"
        meta, title, body = _read(f)
        if meta.get("source") not in SOURCES or not meta.get("sent") or not body:
            continue
        stamp = f"{meta['sent']} {meta.get('sent_time', '')}"
        if name not in found or stamp > found[name]["stamp"]:
            middle = letter_frame.strip_frame(body, profile)
            if middle and len(middle) <= MAX_CHARS:
                found[name] = {"name": name, "title": title, "sent": meta["sent"], "stamp": stamp, "text": middle}
    return sorted(found.values(), key=lambda x: x["stamp"], reverse=True)


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
