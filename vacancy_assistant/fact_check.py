"""Сверка текста модели с резюме: числа и названия, которых нет ни в резюме с «Дополнительно о себе», ни в вакансии.

Модель может приписать опыт, которого нет: число, компанию, технологию. Проверка — без модели, по тексту,
чтобы сама не добавляла ошибок: она не понимает смысла, а только ищет, откуда взялось число или название.
Поэтому это подсказка «проверьте», а не приговор: «на 50%» при «на 30–50%» в резюме она не поймает
(50 в резюме есть), а слово с заглавной в начале предложения не проверяет (не отличить от обычного слова).

- Числа — от 10 (годы, размеры команд, бюджеты, проценты): «1,2» и «1.2» — одно число.
- Названия — в кавычках «…», латиницей с заглавной буквой (SAP, Kubernetes, Deutsche Bank) и русские слова
  с заглавной не в начале предложения или пункта. Название есть в источнике, если каждое его слово совпадает
  со словом источника по началу: «Сбербанке» — «Сбер», «Банке Элемент» — «Банк Элемент».
- Источник — резюме, «Дополнительно о себе», текст вакансии и имена (подпись, кому письмо).
- Слово, в котором модель смешала латиницу и кириллицу одинакового вида («Tехнологическая» с латинской T),
  исправляется по большинству букв (same_script) — и в ответе модели, и перед проверкой.
"""
import re

NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
NAME = re.compile(r"«[^»\n]{2,40}»|[A-Za-z][A-Za-z0-9&+.-]*|[А-ЯЁ][а-яёА-ЯЁ-]{2,}")
WORD = re.compile(r"[a-zа-яё0-9]+", re.I)
MIN_NUMBER = 10
LATIN, CYRILLIC = "ABCEHKMOPTXaceopxy", "АВСЕНКМОРТХасеорху"     # буквы одинакового вида
TO_CYRILLIC, TO_LATIN = str.maketrans(LATIN, CYRILLIC), str.maketrans(CYRILLIC, LATIN)
MIXED = re.compile(r"\w*(?:[A-Za-z]\w*[А-Яа-яЁё]|[А-Яа-яЁё]\w*[A-Za-z])\w*")
URL = re.compile(r"(?:https?://|www\.)\S+|\b[\w.-]+\.(?:ru|com|io|org|net)(?:/\S*)?", re.I)   # ссылки не проверяем


def _same_script(m):
    """Слово из латиницы и кириллицы: буквы меньшинства одинакового вида — буквами большинства."""
    w = m.group(0)
    latin = sum("a" <= c.lower() <= "z" for c in w)
    cyrillic = sum(c.isalpha() for c in w) - latin
    if latin < cyrillic and all(c in LATIN for c in w if "a" <= c.lower() <= "z"):
        return w.translate(TO_CYRILLIC)
    if cyrillic < latin and all(c in CYRILLIC for c in w if c.isalpha() and not "a" <= c.lower() <= "z"):
        return w.translate(TO_LATIN)
    return w


def same_script(text):
    """«Tехнологическая» с латинской T → вся кириллицей; «Kubernetеs» с русской е → вся латиницей.
    Слова, где разные алфавиты не случайны («IT-директор» — это два слова), не меняются."""
    return MIXED.sub(_same_script, text) if text else text


def _num(n):
    return n.replace(",", ".")


def names(text):
    """Названия в тексте: [(начало, название)]."""
    for m in NAME.finditer(text):
        tok = m.group(0).rstrip(".-")
        if tok.startswith("«"):
            yield m.start(), tok
        elif tok[0].isascii():
            if any(c.isupper() for c in tok):
                yield m.start(), tok
        else:
            before = text[:m.start()].rstrip(" \t*_#>")          # разметка Markdown: «## Включить», «**Выделить**»
            if before and before[-1] not in ".!?:—-•\n«(\"[|":
                yield m.start(), tok


class Source:
    """Резюме, «о себе», вакансия и имена — один раз разобранные: проверка многих версий текста не разбирает их заново."""

    def __init__(self, *texts):
        text = "\n".join(t for t in texts if t)
        self.numbers = {_num(n) for n in NUMBER.findall(text)}
        self.words = {w for w in WORD.findall(text.lower().replace("ё", "е"))}
        self.by_start = {}
        for w in self.words:
            if len(w) >= 4:
                self.by_start.setdefault(w[:4], []).append(w)

    def has_word(self, w):
        """Слово есть в источнике — целиком или по началу (окончания и сокращения: «Сбербанке» — «Сбер»)."""
        if w in self.words or w.isdigit():
            return True
        if len(w) < 4:
            return False
        need = lambda s: max(4, min(len(w), len(s)) - 2)
        return any(w[:need(s)] == s[:need(s)] for s in self.by_start.get(w[:4], ()))

    def has_name(self, name):
        words = WORD.findall(name.strip("«»").lower().replace("ё", "е"))
        return bool(words) and all(self.has_word(w) for w in words)

    def unverified(self, text):
        """Чего нет в источнике: [строка, как в тексте] без повторов, по порядку."""
        found, text = [], URL.sub(" ", same_script(text or ""))
        for n in NUMBER.findall(text):
            if float(_num(n)) >= MIN_NUMBER and _num(n) not in self.numbers:
                found.append(n)
        for _, name in names(text):
            if not self.has_name(name):
                found.append(name.strip("«»"))
        return list(dict.fromkeys(found))


def source(profile, vacancy="", *extra):
    """Источник для профиля: резюме с «Дополнительно о себе», вакансия, подпись и имя, extra — например, кому письмо."""
    from .profile import TEXT_FACTS_HEAD
    names = (profile.config.get("письмо") or {}).get("подпись", ""), profile.display_name
    return Source(profile.with_facts(profile.read_resume(), TEXT_FACTS_HEAD), vacancy, *names, *extra)
