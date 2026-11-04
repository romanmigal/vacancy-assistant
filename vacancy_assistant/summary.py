"""Сводка по вакансиям (Сводка.md) для Obsidian и статусы «не обработано / интересно / интервью / архив».

Статус ставится в сводке выпадающим списком (плагин Obsidian Meta Bind). Значения — в свойствах
отдельной заметки vacancy-status.md (s13: yes): сводка остаётся чистой, а статусы переживают
пересборку сводки и повторный разбор. Заметка к вакансии — свойство «заметка» в файле её разбора;
в сводке её показывает поле VIEW.
"""
import re
from datetime import date

from . import funnel, settings
from .errors import AssistantError
from .model import current_model
from .files import (NOTE_PROP, say_decision, ensure_note_prop, md_path, numbered_files, read_meta, read_vacancy, vacancy_number)
from .textio import log_print, read_text, write_text

# Статусы — в этом порядке везде: вкладки окна, выпадающие списки, калибровка, окна «в каких разделах…», сводка.
# Значения — то, что хранится в vacancy-status.md; «Архив» хранится как прежнее «no» (раньше — «Неинтересно»),
# чтобы старые статусы остались на месте.
STATUSES = [("new", "Не обработано"), ("yes", "Интересно"), ("interview", "Интервью"), ("no", "Архив")]
STATUS_NAME_MAX = 20


def statuses(profile=None):
    """Статусы профиля: встроенные и до пяти своих (профиль.json, «статусы») — свои перед «Архивом»."""
    return STATUSES[:-1] + list(getattr(profile, "custom_statuses", [])) + STATUSES[-1:]


def status_key(path):
    """«13 ИТ-директор….md» → «s13»."""
    return f"s{vacancy_number(path)}"


def status_select(profile, key):
    """Выпадающий список статуса (Meta Bind), пишет в свойство key заметки статусов профиля."""
    options = ", ".join(f"option({v}, {n.lower()})" for v, n in statuses(profile))
    return f"`INPUT[inlineSelect({options}):{profile.vault_path(profile.status_file.stem)}#{key}]`"


def _save_custom(profile, items, colors=None):
    profile.custom_statuses = items
    profile.status_colors = {k: (colors or profile.status_colors)[k] for k, _ in items}
    if items:
        profile.config["статусы"] = [{"ключ": k, "название": n, "цвет": profile.status_colors[k]} for k, n in items]
    else:
        profile.config.pop("статусы", None)
    profile.save_config()


def _check_name(profile, name, key=None):
    name = " ".join((name or "").split())
    if not name:
        raise AssistantError("Введите название статуса.")
    if len(name) > STATUS_NAME_MAX:
        raise AssistantError(f"Название статуса — не длиннее {STATUS_NAME_MAX} знаков.")
    if any(n.lower() == name.lower() and k != key for k, n in statuses(profile)):
        raise AssistantError(f"Статус «{name}» уже есть.")
    return name


def add_status(profile, name, color=None):
    """Свой статус — новая вкладка перед «Архивом». Ключ — свободный из c1…c9, при переименовании не меняется.
    color — цвет значка из STATUS_COLORS; не задан — ещё не занятый (поменять можно в списке статусов)."""
    from .profile import MAX_CUSTOM_STATUSES, STATUS_COLORS, free_color
    items = list(profile.custom_statuses)
    if len(items) >= MAX_CUSTOM_STATUSES:
        raise AssistantError(f"Своих статусов — не больше {MAX_CUSTOM_STATUSES}.")
    name = _check_name(profile, name)
    if color and color not in STATUS_COLORS:
        raise AssistantError(f"Неизвестный цвет {color}")
    key = next(f"c{i}" for i in range(1, 10) if f"c{i}" not in dict(items))
    _save_custom(profile, items + [(key, name)], {**profile.status_colors, key: color or free_color(profile.status_colors.values())})
    return key


def rename_status(profile, key, name):
    if key not in dict(profile.custom_statuses):
        raise AssistantError("Встроенные статусы не переименовываются.")
    name = _check_name(profile, name, key)
    _save_custom(profile, [(k, name if k == key else n) for k, n in profile.custom_statuses])


def color_status(profile, key, color):
    """Сменить цвет значка своего статуса."""
    from .profile import STATUS_COLORS
    if key not in dict(profile.custom_statuses):
        raise AssistantError("У встроенных статусов значок не меняется.")
    if color not in STATUS_COLORS:
        raise AssistantError(f"Неизвестный цвет {color}")
    _save_custom(profile, profile.custom_statuses, {**profile.status_colors, key: color})


def order_statuses(profile, keys):
    """Новый порядок своих статусов — порядок их вкладок перед «Архивом». keys — все свои ключи, каждый по разу."""
    have = dict(profile.custom_statuses)
    if not isinstance(keys, list) or sorted(keys) != sorted(have):
        raise AssistantError("Порядок статусов устарел — откройте окно статусов заново.")
    _save_custom(profile, [(k, have[k]) for k in keys])


def delete_status(profile, key, move_to="new"):
    """Удалить свой статус; его вакансии — в раздел move_to (с записью в «Историю»). Возвращает, сколько перенесли."""
    if key not in dict(profile.custom_statuses):
        raise AssistantError("Встроенные статусы не удаляются.")
    if move_to == key or move_to not in dict(statuses(profile)):
        raise AssistantError("Выберите, куда перенести вакансии.")
    moved = [k for k, v in read_statuses(profile).items() if v == key]
    results = numbered_files(profile.results)
    for k in moved:
        set_status(profile, k, move_to)
        if int(k[1:]) in results:
            funnel.record_status(results[int(k[1:])], move_to, profile=profile)
    _save_custom(profile, [(k, n) for k, n in profile.custom_statuses if k != key])
    return len(moved)


def flag_toggle(profile, n):
    """Переключатель флага (Meta Bind): пишет f13: yes / no в заметку статусов — как флаг в окне программы."""
    return f"`INPUT[toggle(onValue(yes), offValue(no)):{profile.vault_path(profile.status_file.stem)}#f{n}]`"


def read_statuses(profile):
    """Статусы: {'s13': 'yes', ...} — из заметки статусов (и, для перехода, из старых свойств сводки)."""
    marks = {}
    for f in (profile.summary, profile.status_file):   # заметка статусов важнее — читаем её последней
        if f.exists():
            m = re.match(r"---\n(.*?)\n---\n", read_text(f), re.S)
            if m:
                marks.update(re.findall(r"""^(s\d+):\s*["']?(\w+)["']?\s*$""", m.group(1), re.M))
    known = dict(statuses(profile))                      # статус удалили (или вписали руками) — «не обработано»
    return {k: v if v in known else "new" for k, v in marks.items()}


def set_status(profile, key, value):
    """Меняет статус вакансии в заметке статусов (для окна программы; в Obsidian это делает Meta Bind)."""
    ensure_statuses(profile, {key: "new"})
    text = read_text(profile.status_file)
    m = re.match(r"---\n(.*?)---\n", text, re.S)
    front = re.sub(rf"^{key}:.*$", f"{key}: {value}", m.group(1), count=1, flags=re.M)
    write_text(profile.status_file, "---\n" + front + "---\n" + text[m.end():])


def read_flags(profile):
    """Номера вакансий, помеченных флагом в окне программы: свойства f13: yes заметки статусов."""
    if not profile.status_file.exists():
        return set()
    m = re.match(r"---\n(.*?)\n---\n", read_text(profile.status_file), re.S)
    return {int(n) for n in re.findall(r"""^f(\d+):\s*["']?yes["']?\s*$""", m.group(1), re.M)} if m else set()


def set_flag(profile, n, on):
    """Ставит или снимает флаг вакансии: строка f13: yes в свойствах заметки статусов."""
    ensure_statuses(profile, {})
    text = read_text(profile.status_file)
    m = re.match(r"---\n(.*?)---\n", text, re.S)
    front = re.sub(rf"^f{n}:.*\n", "", m.group(1), flags=re.M)
    if on:
        front += f"f{n}: yes\n"
    write_text(profile.status_file, "---\n" + front + "---\n" + text[m.end():])


def ensure_statuses(profile, defaults):
    """Добавляет в заметку статусов недостающие ключи (s13: new) и больше ничего не трогает.

    Выбранные статусы пишет Meta Bind в своём формате — скрипт их не переписывает,
    чтобы не испортить текст с кавычками и двоеточиями.
    """
    if profile.status_file.exists():
        text = read_text(profile.status_file)
    else:
        text = ("---\n---\n\n# Статусы вакансий\n\n"
                "Служебная заметка: здесь хранятся статусы (s13) и заметки (n13), которые вы вводите в `Сводка.md`.\n"
                "Ключ — номер вакансии в папке vacancies (13 = «13 …»). Статусы: "
                + ", ".join(f"{v} — {n.lower()}" for v, n in statuses(profile)) + ".\n"
                "Вручную править не нужно.\n")
    m = re.match(r"---\n(.*?)---\n", text, re.S)
    front = m.group(1) if m else ""
    have = set(re.findall(r"^(s\d+):", front, re.M))
    missing = [f"{k}: {v}\n" for k, v in sorted(defaults.items(), key=lambda kv: int(kv[0][1:])) if k not in have]
    if missing or not profile.status_file.exists():
        rest = text[m.end():] if m else text
        write_text(profile.status_file, "---\n" + front + "".join(missing) + "---\n" + rest)


def short_prompt(name):
    """«промпт v6.txt» → «v6» для узкой колонки."""
    m = re.search(r"v\d+", name or "")
    return m.group(0) if m else (name or "?")


def short_salary(s):
    """«от 250 000 до 400 000 ₽ за месяц до вычета налогов» → «250–400 тыс. до налогов»."""
    if not s or s == "не указана":
        return "—"
    nums = [int(n.replace(" ", "").replace(" ", "")) // 1000 for n in re.findall(r"\d[\d  ]*\d", s)]
    if "от" in s and "до" in s and len(nums) == 2:
        amount = f"{nums[0]}–{nums[1]} тыс."
    elif nums:
        amount = ("от " if s.startswith("от") else "до " if s.startswith("до") else "") + f"{nums[0]} тыс."
    else:
        return s
    return amount + (" до налогов" if "вычета" in s else " на руки" if "на руки" in s else "")


def short_decision(d):
    return say_decision(d) if d else d


def short_title(title, limit=55):
    return title if len(title) <= limit else title[:limit - 1].rstrip() + "…"


def added(profile, path):
    """Дата добавления вакансии в список — поле «Сохранено» из её файла, коротко: 16.10."""
    vacancy = profile.vacancies / path.name
    if not vacancy.exists():
        return ""
    saved = read_vacancy(vacancy)[1]["saved"]
    return saved[:5] if saved else ""


def collect_rows(profile):
    """Все разборы профиля с паспортом и статусом, лучшие сверху: [(файл разбора, данные)]."""
    rows = []
    for path in sorted(profile.results.glob("*.md")):   # только верхний уровень
        meta = read_meta(path)
        if meta:
            ensure_note_prop(path)
            rows.append((path, meta))
    statuses = read_statuses(profile)
    for path, r in rows:
        r["status"] = statuses.get(status_key(path), "new")
    rows.sort(key=lambda r: -(r[1]["score"] or 0))      # лучшие сверху
    return rows


def score_cell(r):
    """«**8** (7/9)» для таблицы сводки; вакансия, сохранённая без модели, — «без разбора»."""
    return "без разбора" if r.get("score") is None else f"**{r['score']}** ({r['can']}/{r['want']})"


def stage_cell(path):
    """«Этап» для таблицы сводки: «Интервью с HR 28.10»."""
    f = funnel.read(path)
    return f"{funnel.LABEL[f['stage']]} {date.fromisoformat(f['date']).strftime('%d.%m')}" if f["stage"] and f["date"] else ""


def write_summary(profile, log=None):
    log = log or log_print
    rows = collect_rows(profile)
    key = status_key
    # в ссылках кодируем пробелы и скобки, а из названий убираем [ ] — иначе markdown ломается
    link = lambda p: md_path(p.relative_to(profile.dir).as_posix())
    letter_link = lambda p: f"[письмо]({link(profile.letters / p.name)})" if (profile.letters / p.name).exists() else ""
    for _, r in rows:
        r["title"] = r["title"].replace("[", "(").replace("]", ")")

    ensure_statuses(profile, {key(p): "new" for p, _ in rows})
    lines = [f"# Сводка по вакансиям — {date.today().strftime('%d.%m.%Y')}", "",
             f"Профиль: {profile.display_name}. Модель: {current_model()}, текущий промпт: "
             f"{settings.ANALYSIS_TEMPLATE.name}. Внутри каждой таблицы — по оценке; "
             "в скобках у оценки — «могу/хочу».",
             "⚑ — флаг (тот же, что в окне программы). Статус меняется во второй колонке; "
             "таблицы перераскладываются при следующем запуске  "
             "python3 razbor.py summary  (или любой другой команды скрипта).", ""]
    # Разборы могли быть сделаны разными промптами — оценки из разных версий сравнивать нельзя
    used = sorted({short_prompt(r.get("prompt")) for _, r in rows})   # «промпт v6.txt» и «разбор v6.txt» — одно и то же
    if len(used) > 1:
        lines += [f"> ⚠️ В сводке разборы по разным промптам ({', '.join(used)}). "
                  "Чтобы сравнивать честно, запустите  python3 razbor.py --all", ""]

    for value, name in statuses(profile):
        part = [(p, r) for p, r in rows if r["status"] == value]
        lines += [f"## {name} ({len(part)})", ""]
        if not part:
            lines += ["—", ""]
            continue
        # Узкая таблица: «Могу/Хочу» — в скобках у оценки, ссылки — в одной колонке,
        # колонка «Промпт» — только если в сводке смешаны версии
        prompt_col = len(used) > 1
        lines += ["| ⚑ | Статус | Оценка | Решение | Сохранено | Вакансия | Компания | Зарплата | Этап |"
                  + (" Промпт |" if prompt_col else "") + " Файлы | Комментарии |",
                  "| --- | --- | --- | --- | --- | --- | --- | --- | --- |" + (" --- |" if prompt_col else "") + " --- | --- |"]
        for path, r in part:
            title = short_title(r["title"])
            title = f"[{title}]({r['link']})" if r["link"] else title
            title = f"{key(path)[1:].zfill(2)}. {title}"      # внутренний номер — как в папке vacancies
            files = f"[разбор]({link(path)})" + (f" · {letter_link(path)}" if letter_link(path) else "")
            note = f"`VIEW[{{{profile.vault_path(profile.results.name, path.stem)}#{NOTE_PROP}}}][text]`"
            lines.append(f"| {flag_toggle(profile, vacancy_number(path))} | {status_select(profile, key(path))} | {score_cell(r)} | "
                         f"{short_decision(r['decision'])} | {added(profile, path)} | {title} | "
                         f"{short_title(r['company'], 30)} | {short_salary(r['salary'])} | {stage_cell(path)} |"
                         + (f" {short_prompt(r.get('prompt'))} |" if prompt_col else "")
                         + f" {files} | {note} |")
        lines.append("")

    total = sum(r["seconds"] for _, r in rows)
    lines += [f"Всего вакансий: {len(rows)}. Время модели: {total // 60} мин {total % 60} с."]
    write_text(profile.summary, "\n".join(lines) + "\n")
    counts = ", ".join(f"{n.lower()} — {sum(r['status'] == v for _, r in rows)}" for v, n in statuses(profile))
    log("")
    log(f"Сводка для Obsidian обновлена ({profile.summary.name}): {counts}")
    return rows
