"""Скрытие личных данных перед облачной моделью GigaChat.

С GigaChat резюме, вакансии и письма уходят в Сбер. Перед отправкой программа заменяет в запросе метками:
ФИО человека (из профиля и шапки резюме) — «[Кандидат]», имена знакомых из контактов — «[Контакт 1]»…,
ссылки на личные профили (LinkedIn, Telegram, GitHub, VK…) — «[Ссылка 1]», телефоны, почту, адрес из резюме;
по выключателю в Настройках — и прошлых работодателей из раздела «Опыт» резюме («[Компания 1]»).
Компания вакансии не скрывается: без неё не написать письмо. В ответе модели метки заменяются обратно —
человек видит обычный текст. Для локальной модели ничего не скрывается: данные не уходят с компьютера.

Имена ищутся с падежными окончаниями («Петров», «Петрова», «Петрову») и латиницей («Petrov»).
"""
import re

from . import contacts
from .textio import read_text

NOTE = ("Метки в квадратных скобках ([Кандидат], [Контакт 1], [Компания 1], [Ссылка 1], [Телефон 1], [Почта 1], [Адрес 1]) — "
        "скрытые личные данные. Пиши их в ответе точно так же, в квадратных скобках, не расшифровывай и не склоняй.\n\n")

# Окончания русских имён и фамилий во всех падежах: Петров-а-у-ым-е, Петрова-ой-у, Дмитрий-я-ю-ем-и
ENDINGS = r"(?:а|я|у|ю|е|и|ы|ом|ем|ым|им|ой|ей|ою|ую)?"
PROFILE_LINK = re.compile(
    r"(?:https?://)?(?:www\.)?(?:[a-z]{2}\.)?(?:linkedin\.com/(?:in|pub)/|t\.me/|telegram\.me/|github\.com/|vk\.com/|"
    r"facebook\.com/|fb\.com/|instagram\.com/|habr\.com/(?:ru/)?users/|career\.habr\.com/|x\.com/|twitter\.com/)"
    r"[\w.\-/%]+", re.I)
PHONE = re.compile(r"(?<![\w+])(?:\+7|8)[\s\-(]*\d{3}[\s\-)]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}(?!\d)")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
ADDRESS = re.compile(r"(?:ул\.|улица|пр-т|проспект|пер\.|переулок|бульвар|б-р|шоссе|наб\.|набережная)\s+[^\n,;]{2,40},?\s*"
                     r"(?:д\.|дом)\s*\d+[^\n;]{0,20}", re.I)
EXPERIENCE = re.compile(r"^\*\*(.+?)\*\*\s*·", re.M)       # «**ООО «Пример» (Москва)** · должность · годы»
# выгрузка hh: «### Апрель 2019 — настоящее время (…)», следующей строкой — компания, за ней «Город, сайт»
HH_EXPERIENCE = re.compile(r"^###[^\n]*\d{4}[^\n]*\n+([^\n#*-][^\n]*)(?:\n([^\n]*))?", re.M)
DOMAIN = re.compile(r"(?:https?://)?(?:www\.)?([\w-]+(?:\.[\w-]+)+)/?\s*$")
LABEL = re.compile(r"\[(Кандидат|Контакт|Компания|Ссылка|Телефон|Почта|Адрес)[а-яё]*(?:\s+(\d+))?\]")
LEGAL = re.compile(r"^(?:ООО|ОАО|ПАО|ЗАО|АО|НАО|ИП|ФГУП|ГК|LLC|Ltd|Inc)\.?\s+", re.I)


def _latin(word):
    return "".join(contacts.TRANSLIT.get(ch, ch) for ch in word.lower().replace("ё", "е"))


def _word(word):
    """Шаблон одного слова имени: все падежи и латиница. Короткие слова (инициалы) не берём."""
    w = word.strip(".,«»\"'()")
    if len(w) < 3:
        return None
    if re.fullmatch(r"[а-яё-]+", w, re.I):
        stem = re.sub(r"(?:ий|ый|ой|ая|а|я|й|ь)$", "", w, flags=re.I) or w
        lat = _latin(w).capitalize()
        return rf"(?:{re.escape(w)}|{re.escape(stem)}{ENDINGS}|{re.escape(lat)}(?:a|u|om|e|oy|y)?)"
    return re.escape(w)


def _name_pattern(names, min_words):
    """Имя из нескольких слов (в любом порядке, 1–3 слова подряд). min_words=2 — только имя с фамилией:
    у знакомых одно «Иван» не скрываем, иначе скроется любой Иван в тексте. С учётом регистра: имя пишется
    с большой буквы, а «вера», «надежда», «роман» в тексте вакансии — обычные слова."""
    words = [p for p in (_word(w) for n in names for w in n.split()) if p]
    if not words:
        return None
    one = "(?:" + "|".join(sorted(set(words), key=len, reverse=True)) + ")"
    run = rf"{one}(?:[ \t]+{one}){{{min_words - 1},2}}"
    return re.compile(rf"(?<![\w\[]){run}(?!\w)")


def past_employers(resume):
    """Прошлые работодатели из раздела «Опыт» резюме: названия без формы собственности и города."""
    out = []
    found = [(m.group(1), "") for m in EXPERIENCE.finditer(resume)] + \
            [(m.group(1), m.group(2) or "") for m in HH_EXPERIENCE.finditer(resume)]
    for raw, where in found:
        name = re.sub(r"\s*\([^)]*\)\s*$", "", raw).strip()
        inner = re.search(r"«([^»]{2,60})»|\"([^\"]{2,60})\"", name)
        core = (inner.group(1) or inner.group(2)) if inner else LEGAL.sub("", name).strip()
        site = DOMAIN.search(where.split(",")[-1]) if "," in where else None     # «Санкт-Петербург, szmk.ru/»
        variants = list(dict.fromkeys(v for v in (name, core, site.group(1) if site else "") if v and len(v) >= 3))
        if variants and variants not in out:
            out.append(variants)
    return out


def hide_companies(profile):
    """Скрывать ли прошлых работодателей (выключатель в Настройках; по умолчанию нет: они нужны для оценки опыта)."""
    return bool((profile.config.get("скрытие") or {}).get("компании", False))


def set_hide_companies(profile, on):
    profile.config["скрытие"] = {**(profile.config.get("скрытие") or {}), "компании": bool(on)}
    profile.save_config()


def preview(profile, firms=None, size=1500):
    """Для Настроек: что скрывается и как модель видит начало резюме."""
    m = Mask.for_profile(profile, firms)
    resume = profile.read_resume() if profile.resume.exists() else ""
    text = m.hide(resume[:size])
    kinds = {}
    for kind, _ in m.back:
        kinds[kind] = kinds.get(kind, 0) + 1
    return {"companies": hide_companies(profile), "contacts": len(m.people), "person": bool(m.person),
            "past": [v[0] for v in past_employers(resume)], "found": kinds, "resume": text}


class Mask:
    """Замены для одного профиля: hide(текст) — метки вместо данных, show(ответ) — обратно."""

    def __init__(self, person=(), people=(), companies=(), addresses=()):
        self.person = _name_pattern(person, 1)
        self.person_name = max(person, key=lambda n: len(n.split()), default="")   # в ответ — полное имя
        self.people = [(p, _name_pattern([p], 2)) for p in people if p and len(p.split()) >= 2]
        self.people = [(p, rx) for p, rx in self.people if rx]
        self.companies = [(v[0], re.compile(r"(?<!\w)(?:" + "|".join(re.escape(x) for x in sorted(v, key=len, reverse=True)) + r")(?!\w)", re.I))
                          for v in companies]
        self.addresses = [a for a in addresses if a]
        self.back = {}                     # (вид, номер) → исходный текст

    @classmethod
    def for_profile(cls, profile, firms=None):
        """firms — скрывать ли прошлых работодателей; None — как в настройках профиля."""
        resume = read_text(profile.resume) if profile.resume.exists() else ""
        head = re.match(r"\s*#\s+(.+)", resume)
        person = [n for n in (profile.config.get("имя", ""), head.group(1) if head else "") if n]
        people = list(dict.fromkeys(c.get("name", "").strip() for c in contacts.load(profile)))
        hide_firms = hide_companies(profile) if firms is None else firms
        about = resume + "\n" + "\n".join(profile.read_facts())
        return cls(person, people, past_employers(resume) if hide_firms else (),
                   [m.group(0).strip() for m in ADDRESS.finditer(about)])

    def _label(self, kind, original):
        """Метка для данных: одинаковые данные — одна метка; кандидат один — без номера."""
        n = 0 if kind == "Кандидат" else next((k[1] for k, v in self.back.items() if k[0] == kind and v == original),
                                               sum(1 for k in self.back if k[0] == kind) + 1)
        self.back.setdefault((kind, n), original)
        return f"[{kind} {n}]" if n else f"[{kind}]"

    def hide(self, text):
        for a in self.addresses:
            text = text.replace(a, self._label("Адрес", a))
        text = PROFILE_LINK.sub(lambda m: self._label("Ссылка", m.group(0)), text)
        text = EMAIL.sub(lambda m: self._label("Почта", m.group(0)), text)
        text = PHONE.sub(lambda m: self._label("Телефон", m.group(0)), text)
        for name, rx in self.people:       # знакомые — раньше кандидата: у них может быть то же имя
            text = rx.sub(lambda m, name=name: self._label("Контакт", name), text)
        if self.person:
            text = self.person.sub(lambda m: self._label("Кандидат", self.person_name), text)
        for name, rx in self.companies:
            text = rx.sub(lambda m, name=name: self._label("Компания", name), text)
        return text

    def prompt(self, text):
        """Запрос для облачной модели: со скрытыми данными и пояснением про метки, если что-то скрыто."""
        hidden = self.hide(text)
        return NOTE + hidden if self.back else hidden

    def show(self, text):
        """Ответ модели: метки — обратно в данные. Модель склонила метку («[Кандидата]») — всё равно узнаём."""
        return LABEL.sub(lambda m: self.back.get((m.group(1), int(m.group(2) or 0)), m.group(0)), text)
