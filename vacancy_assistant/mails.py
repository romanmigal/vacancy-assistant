"""Вакансии из писем hh: Автопоиск («Вакансии по подписке: …») и «Подходящие вакансии для резюме: …».

Человек перетаскивает письмо из почты в окно — файл .eml. Программа читает только само письмо и на hh.ru
не ходит: соглашение hh запрещает программы для поиска на сайте, а читать свою почту — нет.
В письме 5–6 вакансий: номер, название, зарплата (не всегда), компания и город.

Ссылки в письмах hh персональные: в каждой — loginkey, ключ входа в аккаунт. Поэтому из ссылки берётся
только номер вакансии; сама ссылка не сохраняется, не открывается и не попадает ни в журнал, ни в окно.
Само письмо программа не хранит. Номера из письма записываются в просмотрено.txt с пометкой «из письма» —
повторное письмо их уже не покажет.
"""
import email
import re
from email import policy
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser

from . import contacts, hh
from .errors import AssistantError
from .files import numbered_files
from .textio import read_text

MARK = "из письма"
KINDS = (("Вакансии по подписке", "Автопоиск"), ("Подходящие вакансии для резюме", "Рекомендации по резюме"))
NOT_HH = ("Это не письмо hh.ru. Программа читает письма hh с новыми вакансиями: «Вакансии по подписке» (Автопоиск) "
          "и «Подходящие вакансии для резюме». Перетащите такое письмо из почты в окно.")
NOT_EML = "Нужен файл письма .eml — перетащите письмо из почтовой программы в окно или в папку, а оттуда — в окно."


class _Cards(HTMLParser):
    """Карточки вакансий: ссылка с названием, строки зарплаты и «компания, город», ссылка «Посмотреть вакансию»."""
    BLOCKS = {"p", "td", "tr", "div", "table", "br", "li", "h1", "h2", "h3"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.cards, self.vid, self.anchor, self.text, self.skip = [], None, None, [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("style", "script", "head"):
            self.skip += 1
        elif tag == "a":
            self._flush()
            m = re.search(r"/vacancy/(\d+)", dict(attrs).get("href") or "")   # только номер; ссылка дальше не идёт
            self.anchor = (m.group(1) if m else None, [])
        elif tag in self.BLOCKS:
            self._flush()

    def handle_endtag(self, tag):
        if tag in ("style", "script", "head"):
            self.skip -= 1
        elif tag == "a" and self.anchor:
            vid, words = self.anchor
            self.anchor = None
            label = " ".join(" ".join(words).split())
            if vid and vid != self.vid:                  # первая ссылка карточки — название вакансии
                self.vid = vid
                self.cards.append({"id": vid, "title": label, "lines": []})
            elif not vid:                                # «Все подходящие вакансии», отписка — карточка кончилась
                self.vid = None
        elif tag in self.BLOCKS:
            self._flush()

    def handle_data(self, data):
        if self.skip:
            return
        (self.anchor[1] if self.anchor else self.text).append(data)

    def _flush(self):
        line = " ".join(" ".join(self.text).split()).strip("‌⠀ ")
        self.text = []
        if line and self.vid and self.cards:
            self.cards[-1]["lines"].append(line)


def _card(c):
    """Строки карточки → зарплата, компания и город. Зарплаты в письме может не быть."""
    salary = next((l for l in c["lines"] if re.search(r"\d.*(₽|руб|\$|€|USD|EUR|KZT|₸)", l)), "")
    rest = [l for l in c["lines"] if l != salary]
    where = rest[0] if rest else ""
    company, _, city = where.partition(", ")
    return {"id": c["id"], "title": c["title"], "salary": " ".join(salary.split()), "company": company.strip(),
            "city": city.split(", м.")[0].strip()}


def read(raw):
    """Письмо (байты .eml) → {"kind", "subject", "date", "items": [{id, title, salary, company, city}]}."""
    try:
        msg = email.message_from_bytes(raw, policy=policy.default)
    except Exception:
        raise AssistantError(NOT_EML)
    sender = str(msg.get("from") or "")
    if not msg.get("subject") and not sender:
        raise AssistantError(NOT_EML)
    if "habr" in sender.lower() or "хабр" in sender.lower():
        raise AssistantError("Это письмо Хабр Карьеры — их программа не разбирает: в них одна вакансия в день и без зарплаты. "
                             "Вакансии Хабра удобнее добавлять по ссылке.")
    if not re.search(r"@(?:[\w-]+\.)*hh\.ru>?\s*$", sender, re.I):
        raise AssistantError(NOT_HH)
    body = msg.get_body(("html", "plain"))
    html = body.get_content() if body else ""
    parser = _Cards()
    parser.feed(html)
    items, seen = [], set()
    for c in parser.cards:
        if c["id"] not in seen and c["title"] and c["title"] != "Посмотреть вакансию":
            seen.add(c["id"])
            items.append(_card(c))
    subject = str(msg.get("subject") or "")
    kind = next((name for start, name in KINDS if subject.startswith(start)), "Письмо hh")
    try:
        when = parsedate_to_datetime(msg["date"]).date().isoformat()
    except (TypeError, ValueError):
        when = ""
    if not items:
        raise AssistantError(f"В письме «{subject}» не нашлось вакансий. Программа читает письма hh с новыми вакансиями: "
                             "«Вакансии по подписке» и «Подходящие вакансии для резюме».")
    return {"kind": kind, "subject": subject, "date": when, "items": items}


def _in_list(profile):
    """Номера вакансий hh, которые уже есть в списке: {номер hh: номер в списке}."""
    out = {}
    if profile.vacancies.is_dir():
        for n, f in sorted(numbered_files(profile.vacancies).items()):
            for vid in re.findall(r"hh\.ru/vacancy/(\d+)", read_text(f)[:2000]):
                out.setdefault(vid, n)
    return out


def inbox(profile, letters):
    """Письма (байты .eml) → что в них нового для профиля. Новые номера — в просмотрено.txt («из письма»).
    {"letters": [{kind, subject, date, count}], "problems": [...], "items": [{…, state, fits, contacts, n}]}
    state: new — новая, seen — уже встречалась (поиск или прежнее письмо), added — уже в списке (n — её номер)."""
    read_ok, problems = [], []
    for name, raw in letters:
        try:
            read_ok.append(read(raw))
        except AssistantError as e:
            problems.append(f"{name}: {e}")
    seen = set(re.findall(r"^(\d+)", read_text(profile.seen), re.M)) if profile.seen.exists() else set()
    added = _in_list(profile)
    people = contacts.load(profile)
    items, ids = [], set()
    for letter in read_ok:
        for it in letter["items"]:
            if it["id"] in ids:
                continue
            ids.add(it["id"])
            state = "added" if it["id"] in added else "seen" if it["id"] in seen else "new"
            items.append({**it, "state": state, "n": added.get(it["id"]), "fits": profile.title_fits(it["title"]),
                          "contacts": sum(1 for c in people if contacts.match_level(it["company"], c.get("company", "")) == 2)})
    new = [(it["id"], it["title"]) for it in items if it["state"] == "new"]
    if new:
        hh.remember_seen(profile, new, MARK)
    return {"letters": [{"kind": l["kind"], "subject": l["subject"], "date": l["date"], "count": len(l["items"])} for l in read_ok],
            "problems": problems, "items": items}
