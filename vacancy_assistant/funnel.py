"""Воронка отклика: этап вакансии с датой, история этапов и история статусов.

Хранится в свойствах файла разбора — рядом с заметкой и референсером, видно и правится в Obsidian:
    этап: Интервью с HR          этап_дата: 2026-10-28
    этапы: Откликнулся 20.10.2026 10:15:02; Ответили 23.10.2026 18:40:11; Интервью с HR 28.10.2026 12:00:45
    статусы: Интересно 20.10.2026 10:15:02; Интервью 28.10.2026 12:00:45
Время — чтобы во вкладке «История» события шли в том порядке, в каком были (у старых записей его нет).
Статусы пишутся, когда их меняют в окне программы; смену статуса в Obsidian программа не видит.
Повторный разбор сохраняет блок свойств целиком, поэтому этапы не теряются.
Правки комментария и референсера — с текстом, поэтому не в свойствах, а в «правки.json» профиля.
Итоги разборов (решение, три оценки, модель, что поменялось) — в «история разборов.json» профиля (#59):
файл разбора при «Разобрать заново» переписывается, а история остаётся.
"""
import re
from datetime import date, datetime, timedelta

from .errors import AssistantError
from .files import read_prop, set_prop
from .textio import read_json, write_json

STAGES = [("applied", "Откликнулся"), ("answered", "Ответили"), ("hr", "Интервью с HR"),
          ("manager", "Интервью с руководителем"), ("final", "Финал"), ("offer", "Оффер"),
          ("rejected", "Отказ"), ("silent", "Не ответили")]
LABEL = dict(STAGES)
KEY = {v: k for k, v in STAGES}
INTERVIEW = {"hr", "manager", "final", "offer"}     # раздел «Интервью» ставится сам
ARCHIVE = {"rejected", "silent"}                   # предложить перенести в Архив
PROPS = ("этап", "этап_дата", "этапы")
STATUS_PROP = "статусы"
EDITS_FILE = "правки.json"                         # {"<имя файла вакансии>": [{date, time, field, text, from, last}, …]}
EDIT_FIELDS = ("comment", "referrer")
EDIT_PAUSE = timedelta(minutes=10)                 # сохранения поля чаще — одна правка (комментарий сохраняется сам)


def parse_date(s):
    """«2026-10-28» или «28.10.2026» → date; пусто или не дата — None."""
    s = (s or "").strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
            return date.fromisoformat(s)
        m = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", s)
        return date(int(m[3]), int(m[2]), int(m[1])) if m else None
    except ValueError:
        return None


def dated(text, names, keep=False):
    """«Откликнулся 20.10.2026 10:15:02; Ответили 23.10.2026» → [(ключ, "2026-10-20", "10:15:02"), (…, "")];
    names — {название: ключ}; keep — незнакомое название оставить как есть, а не пропустить.
    Время необязательно: у записей до версии со временем его нет."""
    out = []
    for part in text.split(";"):
        m = re.fullmatch(r"\s*(.+?)\s+(\d{1,2}\.\d{1,2}\.\d{4})(?:\s+(\d{1,2}:\d{2}(?::\d{2})?))?\s*", part)
        if m and (m[1] in names or keep) and parse_date(m[2]):
            out.append((names.get(m[1], m[1]), parse_date(m[2]).isoformat(), m[3] or ""))
    return out


def moment(when):
    """date или datetime (по умолчанию — сейчас) → ("2026-10-20", "10:15:02"); у даты без времени — ""."""
    when = when or datetime.now()
    return (when.date().isoformat(), when.strftime("%H:%M:%S")) if isinstance(when, datetime) else (when.isoformat(), "")


def stamp(d, t):
    """("2026-10-20", "10:15:02") → «20.10.2026 10:15:02» — как в свойствах разбора."""
    return f"{date.fromisoformat(d).strftime('%d.%m.%Y')}{' ' + t if t else ''}"


def status_names(profile=None):
    from .summary import statuses                   # summary сама зовёт funnel — импорт здесь, без цикла
    return dict(statuses(profile))


def read(path):
    """Этап, история этапов и история статусов вакансии (разбор не создан — всё пусто)."""
    if not path.exists():
        return {"stage": "", "date": "", "history": [], "statuses": []}
    history = [{"stage": k, "date": d, "time": t} for k, d, t in dated(read_prop(path, "этапы"), KEY)]
    # Свой статус профиля (#48) остаётся в истории своим названием — как назывался в момент смены
    statuses = [{"status": k, "date": d, "time": t}
                for k, d, t in dated(read_prop(path, STATUS_PROP), {v: k for k, v in status_names().items()}, keep=True)]
    stage = KEY.get(read_prop(path, "этап"), "")
    d = parse_date(read_prop(path, "этап_дата"))
    return {"stage": stage, "date": d.isoformat() if d else "", "history": history, "statuses": statuses}


def record_status(path, status, when=None, profile=None):
    """Запомнить смену статуса с датой и временем — для вкладки «История». profile — для своих статусов."""
    if not path.exists():
        return
    old = read_prop(path, STATUS_PROP)
    entry = f"{status_names(profile)[status]} {stamp(*moment(when))}"
    set_prop(path, STATUS_PROP, f"{old}; {entry}" if old else entry)


def write(path, f):
    history = "; ".join(f"{LABEL[h['stage']]} {stamp(h['date'], h.get('time', ''))}" for h in f["history"])
    for prop, value in zip(PROPS, (LABEL.get(f["stage"], ""), f["date"], history)):
        if value or read_prop(path, prop):
            set_prop(path, prop, value)


def set_stage(path, stage, when=None, status=""):
    """Новый этап с датой и временем (по умолчанию — сейчас; when — date без времени или datetime).
    Тот же этап ещё раз — поправить дату. Пустой этап — снять.
    Возвращает (воронка, новый раздел или "", предложить ли Архив). status — нынешний раздел вакансии."""
    if stage and stage not in LABEL:
        raise AssistantError(f"Неизвестный этап «{stage}»")
    d, t = moment(when)
    f = read(path)
    if not stage:
        f.update(stage="", date="")
    elif f["history"] and f["history"][-1]["stage"] == stage:
        f["history"][-1].update(date=d, time=t)                          # тот же этап — поправили дату
        f["date"] = d
    else:
        f["history"].append({"stage": stage, "date": d, "time": t})
        f.update(stage=stage, date=d)
    write(path, f)
    section = ("interview" if stage in INTERVIEW and status != "interview"
               else "yes" if stage == "applied" and status == "new" else "")
    return f, section, stage in ARCHIVE and status != "no"



def all_edits(profile):
    """Правки всех вакансий профиля: {имя файла без .md: [правки]} — для таблицы, одним чтением."""
    f = profile.dir / EDITS_FILE
    return read_json(f) if f.exists() else {}


def read_edits(profile, path):
    """Правки комментария и референсера вакансии: [{date, time, field, text}], старые сверху."""
    return all_edits(profile).get(path.stem, [])


def updated(f, edits):
    """Когда вакансию последний раз двигали — «2026-10-28» или "": позднее из смены этапа (f — read())
    и правки комментария (edits — правки этой вакансии). Статус, флаг и референсер не считаются."""
    dates = [h["date"] for h in (f or {}).get("history", [])]
    dates += [(e.get("last") or e["date"])[:10] for e in edits or [] if e.get("field") == "comment"]
    return max(dates, default="")


def record_edit(profile, path, field, text, before="", when=None):
    """Запомнить новый текст комментария или референсера (before — что было в поле). Сохранения одного поля
    с паузами меньше EDIT_PAUSE — одна правка: время — когда начали, текст — последний (комментарий сохраняется
    сам на каждой паузе в наборе, и пауза не должна становиться событием)."""
    if field not in EDIT_FIELDS:
        raise AssistantError(f"Неизвестное поле «{field}»")
    f = profile.dir / EDITS_FILE
    data = read_json(f) if f.exists() else {}
    items = data.setdefault(path.stem, [])
    now = when or datetime.now()
    text = " ".join((text or "").split())
    mine = [e for e in items if e["field"] == field]
    last = mine[-1] if mine and mine[-1].get("last") else None
    going = last and isinstance(now, datetime) and now - datetime.fromisoformat(last["last"]) < EDIT_PAUSE
    if going:                                        # продолжение той же правки — на её месте
        earlier = mine[-2]["text"] if len(mine) > 1 else last.get("from", "")
        if text == earlier:
            items.remove(last)                       # вернули как было — правки нет
        else:
            last.update(text=text, last=now.isoformat(timespec="seconds"))
    else:
        start = " ".join((before or "").split())    # текст до начала правки
        if text != (mine[-1]["text"] if mine else start):
            d, t = moment(now)
            items.append({"date": d, "time": t, "field": field, "text": text, "from": start,
                          "last": now.isoformat(timespec="seconds") if isinstance(now, datetime) else ""})
    if not items:
        data.pop(path.stem)
    write_json(f, data)


# ---------- история разборов (#59) ----------

ANALYSES_FILE = "история разборов.json"           # {"<имя файла вакансии>": [{date, time, decision, score, can, want, …}, …]}
INPUTS = (("criteria", "критерии"), ("resume", "резюме"), ("facts", "о себе"))


def record_analysis(profile, path, meta, hashes, when=None):
    """Дописать итог разбора в историю: когда, решение, оценки, модель и отпечатки критериев, резюме и «о себе».
    Разборы, сделанные до этой версии, в историю не попадают — она копится с первого нового разбора."""
    f = profile.dir / ANALYSES_FILE
    data = read_json(f) if f.exists() else {}
    d, t = moment(when)
    data.setdefault(path.stem, []).append(
        {"date": d, "time": t, **{k: meta.get(k) for k in ("decision", "score", "can", "want", "model", "stage")}, **hashes})
    write_json(f, data)


# ---------- история своих оценок ----------

RATINGS_FILE = "история моих оценок.json"          # {"<имя файла вакансии>": [{date, time, score, can, want, decision, reason}, …]}
RATING_KEYS = ("score", "can", "want", "decision", "reason")


def record_rating(profile, path, rating, when=None):
    """Дописать свою оценку вакансии в историю («Мои оценки», калибровка). Та же оценка ещё раз — не событие:
    калибровка сохраняет оценку и тогда, когда её только пролистали."""
    f = profile.dir / RATINGS_FILE
    data = read_json(f) if f.exists() else {}
    items = data.setdefault(path.stem, [])
    entry = {k: rating.get(k) for k in RATING_KEYS}
    if items and {k: items[-1].get(k) for k in RATING_KEYS} == entry:
        return
    d, t = moment(when)
    items.append({"date": d, "time": t, **entry})
    write_json(f, data)


def read_ratings(profile, path):
    """История своих оценок вакансии, старые сверху."""
    f = profile.dir / RATINGS_FILE
    return (read_json(f) if f.exists() else {}).get(path.stem, [])


def all_analyses(profile):
    """История разборов всех вакансий: {имя файла без .md: [записи]} — одним чтением."""
    f = profile.dir / ANALYSES_FILE
    return read_json(f) if f.exists() else {}


def read_analyses(profile, path):
    """История разборов вакансии, старые сверху; у каждой записи — changed: что поменялось с прошлого разбора
    (["критерии", "резюме"…]; None — неизвестно: у прошлой записи нет отпечатков)."""
    f = profile.dir / ANALYSES_FILE
    items = (read_json(f) if f.exists() else {}).get(path.stem, [])
    out = []
    for i, e in enumerate(items):
        prev = items[i - 1] if i else None
        known = prev is not None and all(k in prev and k in e for k, _ in INPUTS)
        out.append({**e, "changed": [name for k, name in INPUTS if prev[k] != e[k]] if known else None})
    return out
