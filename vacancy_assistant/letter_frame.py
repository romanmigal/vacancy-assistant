"""Рамка сопроводительного письма: приветствие, фраза о готовности, завершение и подпись ставит программа.

Модель пишет только середину письма. Раньше обязательные фразы писала она сама — и подпись бралась то из профиля,
то из резюме («Мигаль Роман Анатольевич»), а «Могу приступить сразу» стояла всегда, даже когда её убирают.

- Приветствие — из шаблона письма (первая строка, если это приветствие): у каждого шаблона может быть своё.
- Готовность, завершение и подпись — из настроек профиля («письмо»); пустая готовность — фразы нет.
- То, что модель всё же написала сама (приветствие в начале, готовность, завершение и подпись в конце), убираем.
"""
import re

GREETING = re.compile(r"^(?:здравствуйте|добрый\s+(?:день|вечер)|доброе\s+утро|приветствую|привет|уважаем\w*)\b[^\n]{0,60}$",
                      re.I)
AVAILABILITY = re.compile(r"^(?:могу|готова?)\s+(?:приступить|выйти)[^.!\n]*[.!]?\s*", re.I)
CLOSING = re.compile(r"^(?:буду\s+рада?|с\s+уважением|спасибо|благодарю|готова?\s+(?:обсудить|рассказать)|"
                     r"буду\s+признательн|жду\s+(?:вашего\s+)?ответа|хорошего\s+дня)", re.I)
LABEL = re.compile(r"^\[[^\]\n]{1,30}\]$")          # метка маски вместо подписи: «[Кандидат]», у GigaChat и с латинской C
NAME = re.compile(r"^[A-ZА-ЯЁ][a-zа-яё]+(?:-[A-ZА-ЯЁ][a-zа-яё]+)?(?:\s+[A-ZА-ЯЁ][a-zа-яё]+(?:-[A-ZА-ЯЁ][a-zа-яё]+)?){1,2}$")


def _settings(profile):
    l = profile.config["письмо"]
    return (l.get("готовность") or "").strip(), (l.get("завершение") or "").strip(), (l.get("подпись") or "").strip()


def _is_name(line, profile):
    """Подпись: подпись или имя из профиля, либо два-три слова с заглавной — имя и фамилия (с отчеством)."""
    line = line.strip().rstrip(",")
    own = {x.strip().lower() for x in (_settings(profile)[2], profile.display_name) if x}
    return line.lower() in own or bool(NAME.match(line))


def strip_frame(text, profile):
    """Середина письма: без приветствия в начале и без готовности, завершения и подписи в конце."""
    lines = (text or "").strip().split("\n")
    while lines and (not lines[0].strip() or GREETING.match(lines[0].strip())):
        lines.pop(0)
    availability, closing, _ = _settings(profile)
    while lines:
        line = lines[-1].strip()
        if not line or _is_name(line, profile) or LABEL.match(line) or CLOSING.match(line) or (closing and line == closing):
            lines.pop()
            continue
        rest = AVAILABILITY.sub("", line, count=1) if AVAILABILITY.match(line) else None
        if rest is None and availability and line.startswith(availability):
            rest = line[len(availability):].strip()
        if rest is None:
            break
        if rest:                       # «Могу приступить сразу. Удалённый формат мне подходит.» — остаток проверяем дальше
            lines[-1] = rest
            continue
        lines.pop()
    return "\n".join(lines).strip()


def split_example(example, profile):
    """Шаблон письма → (приветствие, середина): модели — только середина как образец, приветствие — в письмо."""
    lines = (example or "").strip().split("\n")
    greeting = lines[0].strip() if lines and GREETING.match(lines[0].strip()) else ""
    return greeting, strip_frame(example, profile)


FORMAT = re.compile(r"формат|удал[её]нн|гибрид|офис|релокац|командиров", re.I)


def assemble(profile, greeting, body):
    """Письмо целиком: приветствие из шаблона, середина от модели, готовность, завершение и подпись из профиля.
    Согласие с форматом работы в конце середины — одной строкой с готовностью, как в образце:
    «Могу приступить сразу. Удалённый формат мне подходит.»"""
    availability, closing, signature = _settings(profile)
    paras = body.strip().split("\n\n")
    last = paras[-1].strip()
    if availability and len(paras) > 1 and "\n" not in last and len(last) <= 120 and not last.startswith("—") and FORMAT.search(last):
        paras, availability = paras[:-1], f"{availability} {last}"
    return "\n\n".join(x for x in (greeting, "\n\n".join(paras).strip(), availability, closing, signature) if x)
