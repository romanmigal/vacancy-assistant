"""Таблица своих оценок (мои-оценки.md) — эталон для настройки критериев.

После причины — дата, когда оценку поставили или поменяли: по ней колонка «Моя оценка» в таблице
сортирует свежие оценки наверх. Дальше — «Могу» и «Хочу»: свою оценку ставят раздельно, как модель,
а общая — расчётная (total). В таблицах прежних версий этих колонок нет — они добавляются при первой записи;
у старых оценок дата, «Могу» и «Хочу» пустые, общая — как была.
"""
import re
from datetime import date

from .errors import AssistantError
from .files import decision_word, numbered_files, read_vacancy
from .textio import log_print, read_text, write_text

RATINGS_HEADER = """# Мои оценки вакансий

Эталон для настройки критериев: сначала оцениваю сам, **до** того как смотреть ответы модели.

**Шкала:** 1 — совсем не моё, 10 — идеально подходит.
**Откликаться:** да / нет / да, но с оговорками.

| №   | Вакансия | Моя оценка (1–10) | Откликаться? | Почему (1–2 фразы) | Дата | Могу | Хочу |
| --- | -------- | ----------------- | ------------ | ------------------ | ---- | ---- | ---- |
"""
EXTRA_COLUMNS = ["Дата", "Могу", "Хочу"]          # колонки после «Почему» — по порядку, как появлялись
DATE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")


def parse_numbers(args):
    """«17 18 20-25» → [17, 18, 20, 21, 22, 23, 24, 25]."""
    nums = []
    for a in args:
        for part in a.split(","):
            if re.fullmatch(r"\d+-\d+", part):
                lo, hi = map(int, part.split("-"))
                nums += range(lo, hi + 1)
            elif part.isdigit():
                nums.append(int(part))
            elif part:
                raise AssistantError(f"Не понял номер «{part}». Пример: ratings 17 18 20-25")
    return nums


def fill_ratings(profile, numbers=None, log=None):
    """Добавляет в мои-оценки.md строки для вакансий: номер и название заполнены, оценки — пустые.
    Оценку модели сюда намеренно не пишем — чтобы она не подсказывала вашу. Возвращает добавленные номера."""
    log = log or log_print
    path = profile.ratings
    if not path.exists():
        write_text(path, RATINGS_HEADER)
    lines = read_text(path).splitlines()
    table = [i for i, l in enumerate(lines) if l.startswith("|")]
    if len(table) < 2:
        raise AssistantError(f"В {path.name} не нашёл таблицу с заголовком — добавьте её или удалите файл, "
                             "он создастся заново.")
    first, last = table[0], table[-1]
    have = [c.strip() for c in lines[first].strip().strip("|").split("|")]
    for name in EXTRA_COLUMNS:                           # таблица прежней версии — недостающие колонки в конец
        if name not in have:
            lines[first] = lines[first].rstrip().rstrip("|").rstrip() + f" | {name} |"
            lines[first + 1] = lines[first + 1].rstrip().rstrip("|").rstrip() + " | ---- |"
    rows = {}
    for l in lines[first + 2:last + 1]:
        m = re.match(r"\|\s*(\d+)\s*\|", l)
        if m:
            rows[int(m.group(1))] = l                    # свои строки — как есть, с вашими оценками

    available = numbered_files(profile.vacancies)
    wanted = list(numbers or []) or sorted(available)
    added = []
    for n in wanted:
        if n in rows:
            continue
        if n not in available:
            log(f"{n:02d}: нет такой вакансии в {profile.vacancies.name}/ — пропускаю")
            continue
        info = read_vacancy(available[n])[1]
        name = f"{info['title']} — {info['company']}".replace("|", "/")
        rows[n] = f"| {n:02d}  | {name} |  |  |  |  |  |  |"
        added.append(n)

    lines = lines[:first + 2] + [rows[n] for n in sorted(rows)] + lines[last + 1:]
    write_text(path, "\n".join(lines) + "\n")
    log(f"{path.name}: добавлено строк — {len(added)}" + (f" ({', '.join(f'{n:02d}' for n in added)})" if added else "")
        + ". Заполните оценку, решение и причину.")
    return added


def read_reference(profile):
    """Эталон из мои-оценки.md: {номер: {score, yes, reason, name}} — только строки с решением."""
    from .files import decision_yes
    path = profile.ratings
    if not path.exists():
        raise AssistantError("Нет мои-оценки.md. Сначала: python3 razbor.py ratings — и заполните свои оценки.")
    ref = {}
    for line in read_text(path).splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 5 or not cells[0].isdigit():
            continue
        yes = decision_yes(cells[3])
        if yes is None:
            continue
        score = int(cells[2]) if cells[2].isdigit() else None
        ref[int(cells[0])] = {"score": score, "yes": yes, "decision": decision_word(cells[3]), "reason": cells[4], "name": cells[1]}
    return ref


DECISIONS = {"да": "да", "возможно": "да, но с оговорками", "нет": "нет"}


def total(can, want, decision):
    """Общая своя оценка из «Могу», «Хочу» и решения — по тем же правилам, что шаблон разбора задаёт модели:
    середина между «Могу» и «Хочу», но не выше меньшей из них плюс 1; при «нет» — не выше 4."""
    score = min(int((can + want) / 2 + 0.5), min(can, want) + 1)
    return min(score, 4) if decision == "нет" else score


def read_rows(profile):
    """Все строки мои-оценки.md, и заполненные, и пустые: {номер: {score, decision, reason, name, date, can, want}};
    date — ISO («2026-11-03») или пусто, если оценку ставили до появления даты; can, want — None у старых оценок."""
    if not profile.ratings.exists():
        return {}
    rows = {}
    for line in read_text(profile.ratings).splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 5 and cells[0].isdigit():
            day = DATE.fullmatch(cells[5]) if len(cells) > 5 else None
            number = lambda i: int(cells[i]) if len(cells) > i and cells[i].isdigit() else None
            rows[int(cells[0])] = {"score": number(2), "decision": cells[3], "reason": cells[4], "name": cells[1],
                                   "date": f"{day.group(3)}-{day.group(2)}-{day.group(1)}" if day else "",
                                   "can": number(6), "want": number(7)}
    return rows


def set_rating(profile, n, can, want, decision, reason="", today=None, when=None):
    """Записывает свою оценку вакансии в мои-оценки.md (строка добавляется, если её нет) с сегодняшней датой:
    «Могу», «Хочу», решение и причину; общая — расчётная (total)."""
    try:
        can, want = int(can), int(want)
    except (TypeError, ValueError):
        raise AssistantError("Поставьте «Могу» и «Хочу» — от 1 до 10.") from None
    if not (1 <= can <= 10 and 1 <= want <= 10):
        raise AssistantError("«Могу» и «Хочу» — от 1 до 10.")
    if decision not in DECISIONS:
        raise AssistantError("Решение — да, возможно или нет.")
    score = total(can, want, decision)
    fill_ratings(profile, [n], log=lambda *_: None)
    clean = lambda t: " ".join(str(t or "").split()).replace("|", "/")
    lines = read_text(profile.ratings).splitlines()
    for i, line in enumerate(lines):
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 5 and cells[0].isdigit() and int(cells[0]) == n:
            lines[i] = (f"| {n:02d}  | {cells[1]} | {score} | {DECISIONS[decision]} | {clean(reason)} | "
                        f"{(today or date.today()).strftime('%d.%m.%Y')} | {can} | {want} |")
    write_text(profile.ratings, "\n".join(lines) + "\n")
    path = numbered_files(profile.vacancies).get(n)
    if path:                                            # и в «Историю» вакансии
        from . import funnel
        funnel.record_rating(profile, path, {"score": score, "can": can, "want": want, "decision": decision,
                                             "reason": clean(reason)}, when)
    return score
