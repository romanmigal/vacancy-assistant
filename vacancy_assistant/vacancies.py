"""Вакансии профиля для окна: строки таблицы, карточка вакансии, какие оценки устарели.

Читает те же файлы профиля, что командная строка и Obsidian: vacancies/, results/, письма и статусы.
"""
import json
import re
import sys
from datetime import datetime

from . import actual, analysis, answer, artifacts, company, contacts, fact_check, funnel, letter_templates, ratings, similar, sites, summary
from .errors import AssistantError
from .files import (REFERRER_ID_PROP, REFERRER_PROP, analysis_body, numbered_files, read_meta, read_note, read_prop,
                    read_vacancy, strip_service)
from .textio import read_text

def without_saved(text):
    """Текст вакансии для карточки — без служебных строк шапки: даты, ещё ссылки и пометка о дубле видны рядом со ссылкой."""
    return re.sub(r"[ \t]*\n\*\*(?:Опубликовано|Сохранено|Ещё ссылки|Возможно, дубль):\*\*[^\n]*", "", text, count=4)


def parsed_analysis(result):
    """Разбор по разделам для карточки; числа оценок — из паспорта, те же, что в таблице."""
    if not result.exists():
        return None
    p = answer.parse(analysis_body(read_text(result)))
    meta = read_meta(result) or {}
    for key, field in answer.META.items():
        if meta.get(field) is not None:
            p[key] = {"score": meta[field], "why": p[key]["why"] if p[key] else []}
    return p


def salary_value(salary):
    """Число для сортировки по зарплате, в тысячах: верх вилки (сколько можно получить); None — не указана."""
    nums = [int(re.sub(r"\D", "", n)) // 1000 for n in re.findall(r"\d[\d\s]*\d", salary or "")]
    return max(nums) if nums else None


def date_key(saved):
    """«16.10.2026» → «2026-10-16» для сортировки по дате."""
    m = re.match(r"(\d{2})\.(\d{2})\.(\d{4})", saved or "")
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else ""


def criteria_names(profile):
    """{"1": ("Локация", "Локация: Москва или удалённо…")} — короткое имя жёсткого критерия и его текст."""
    if not profile.criteria_file.exists():
        return {}
    names = {}
    for n, text in re.findall(r"^К(\d+)\.\s*(.+)$", profile.read_criteria(), re.M):
        short = re.split(r"[:.(—]", text, 1)[0].strip()
        names[n] = (short[:40], text.strip())
    return names


def violations(text, names):
    """Нарушенные жёсткие критерии из разбора: [{"n": "1", "name": "Локация", "text": …}]."""
    return [{"n": n, "name": names.get(n, ("", ""))[0], "text": names.get(n, ("", ""))[1]}
            for n in re.findall(r"^\**К(\d+):\**\s*❌", text, re.M)]


def my_rating(r):
    """Своя оценка для строки таблицы: {my_score, my_can, my_want, my_decision (да / возможно / нет), my_date (ISO),
    my_reason} — пусто, если вакансию сами не оценивали."""
    word = ratings.decision_word((r or {}).get("decision"))
    if not word:
        return {"my_score": None, "my_can": None, "my_want": None, "my_decision": "", "my_date": "", "my_reason": ""}
    return {"my_score": r["score"], "my_can": r.get("can"), "my_want": r.get("want"), "my_decision": word,
            "my_date": r.get("date", ""), "my_reason": r.get("reason", "")}


def vacancy_rows(profile):
    """Все вакансии профиля — и разобранные, и ждущие разбора — для таблицы в окне."""
    statuses = summary.read_statuses(profile)
    names = criteria_names(profile)
    flags = summary.read_flags(profile)
    current = current_inputs(profile)
    edits = funnel.all_edits(profile)
    found = artifacts.types(profile)                   # артефакты вакансии — колонка «Артефакты», письмо в «Статистике»
    analyses = current["analyses"]                     # первый разбор — для «Статистики»
    firms = company.load(profile)                      # агентства и работодатели hh
    mine = ratings.read_rows(profile)                  # своя оценка — колонка «Моя оценка»
    rows, texts = [], {}
    for n, path in sorted(numbered_files(profile.vacancies).items()):
        result = profile.results / path.name
        meta = read_meta(result) if result.exists() else None
        vacancy_text, vacancy_info = read_vacancy(path)
        texts[n] = vacancy_text
        info = meta or vacancy_info
        is_agency, agency_why, agency_what = company.agency(firms, info.get("company", ""), vacancy_text, company.employer_id(vacancy_info))
        progress = funnel.read(result) if meta else None
        rows.append({
            "n": n,
            "flag": n in flags,
            "title": info.get("title", path.stem),
            "company": info.get("company", ""),
            "agency": is_agency, "agency_why": agency_why, "agency_what": agency_what,   # агентство и почему так решили
            "source": sites.source(info.get("link", ""), info.get("company", "")),      # HH, Хабр Карьера, Сайт МТС…
            "people_query": sites.people_query(info.get("company", "")),                 # поиск людей в LinkedIn и Сетке
            "salary": summary.short_salary(info.get("salary")),
            "salary_value": salary_value(info.get("salary")),
            "added_key": date_key(vacancy_info["saved"]),
            "link": info.get("link", ""),
            "added": vacancy_info["saved"][:10],
            "posted": vacancy_info["posted"][:10],                      # дата публикации на сайте
            "posted_key": date_key(vacancy_info["posted"]),
            "more_links": [{"url": u, "source": sites.source(u, info.get("company", ""))}           # та же вакансия на других сайтах
                           for u in re.split(r"[ ,]+", vacancy_info["more"]) if u.startswith("http")],
            "maybe_dupe": int(vacancy_info["maybe"]) if vacancy_info["maybe"].isdigit() else None,
            "analyzed": bool(meta),
            "analyzed_on": min([e["date"] for e in analyses.get(result.stem, [])] + [meta.get("date") or ""] if meta else [""],
                               key=lambda d: d or "9999"),       # первый разбор: история разборов или паспорт
            "scored_on": (meta.get("date") or "")[:10] if meta else "",  # последний разбор — от него оценка модели
            "score": meta.get("score") if meta else None,
            "can": meta.get("can") if meta else None,
            "want": meta.get("want") if meta else None,
            "decision": meta.get("decision", "") if meta else "",
            **my_rating(mine.get(n)),
            "status": statuses.get(f"s{n}", "new"),
            "note": read_note(result) if meta else "",
            "referrer": read_prop(result, REFERRER_PROP) if meta else "",
            "referrer_id": read_prop(result, REFERRER_ID_PROP) if meta else "",
            "funnel": progress,                                       # этап отклика и история этапов
            "updated": funnel.updated(progress, edits.get(result.stem)) if meta else "",   # этап или комментарий
            "actual": actual.read(result) if meta else None,               # открыта ли на сайте — по «Разобрать заново»
            "letter": (profile.letters / path.name).exists() or (profile.referrer_letters / path.name).exists(),
            "artifacts": len(found.get(path.stem, [])),
            "cover_sent": "cover" in found.get(path.stem, []),            # письмо с отметкой «Отправлено»
            "stage": meta.get("stage", "full") if meta else "",
            "model": meta.get("model", "") if meta else "",                 # кто оценивал: gemma…, GigaChat…
            "criteria_changed": criteria_changed(profile, result, meta, current),
            "violations": violations(read_text(result), names) if meta else [],
        })
    like = similar.bonuses(rows, texts) if similar.enabled(profile) else {}   # «Хочу» выше у похожих на отклики
    for r in rows:
        r["want_bonus"], r["want_like"] = like.get(r["n"], {}).get("bonus", 0), like.get(r["n"], {}).get("like", [])
    people = contacts.load(profile)                    # сколько знакомых в компании вакансии — значок в таблице
    by_id, syn = {c["id"]: c for c in people}, contacts.synonyms(profile)
    exact = contacts.exact_counter(people, syn)
    for r in rows:
        r["contacts"] = exact(r["company"])
        linked = by_id.get(r.pop("referrer_id", ""))  # референсер из контактов — имя и должность, остальное в подсказке
        r["referrer_contact"] = contacts.brief(linked) if linked else None
    rows.sort(key=lambda r: (not r["analyzed"], -(r["score"] or 0), r["n"]))
    return rows


def vacancy_file(profile, n, folder=None, missing=None):
    """Файл вакансии по номеру — из vacancies/ или другой папки профиля (разборы); нет такого — ошибка."""
    n = int(n)
    files = numbered_files(folder or profile.vacancies)
    if n not in files:
        raise AssistantError(missing or f"Нет вакансии с номером {n}")
    return files[n]


def with_status(profile, statuses):
    """Имена файлов вакансий с одним из статусов (new / yes / no)."""
    marks = summary.read_statuses(profile)
    return [f.name for n, f in numbered_files(profile.vacancies).items() if marks.get(f"s{n}", "new") in statuses]


def current_inputs(profile):
    """Отпечатки того, по чему оценивают сейчас: критерии с «о себе» и резюме — для criteria_changed."""
    return {"criteria": profile.criteria_hash(), "resume": profile.resume_hash(), "analyses": funnel.all_analyses(profile)}


def criteria_changed(profile, result, meta=None, current=None):
    """Оценка сделана по другим данным, чем сейчас: критериям, «Дополнительно о себе» или резюме. В новых оценках —
    отпечатки; в старых отпечатка критериев нет — смотрим, не правили ли критерии после оценки, а отпечаток резюме
    берём из истории разборов, если вакансию разбирали после её появления.
    meta и current (current_inputs) — чтобы не читать их заново для каждой строки таблицы."""
    meta = meta if meta is not None else (read_meta(result) if result.exists() else None)
    if not meta or not profile.criteria_file.exists() or meta.get("stage") == analysis.NO_MODEL:
        return False
    current = current or current_inputs(profile)
    if meta.get("criteria_hash") and meta["criteria_hash"] != current["criteria"]:
        return True
    if not meta.get("criteria_hash") and profile.criteria_file.stat().st_mtime > result.stat().st_mtime:
        return True
    history = current["analyses"].get(result.stem) or [{}]
    resume = meta.get("resume_hash") or history[-1].get("resume")
    return bool(resume) and resume != current["resume"]


def changed_with_status(profile, statuses):
    """Имена файлов вакансий с одним из статусов, оценённых по прежним критериям, «о себе» или резюме."""
    current = current_inputs(profile)
    return [n for n in with_status(profile, statuses)
            if criteria_changed(profile, profile.results / n, current=current)]


def analyzed_with_status(profile, statuses):
    """Имена файлов разобранных моделью вакансий с одним из статусов — «пересчитать все»."""
    def analyzed(name):
        meta = read_meta(profile.results / name) if (profile.results / name).exists() else None
        return bool(meta) and meta.get("stage") != analysis.NO_MODEL
    return [n for n in with_status(profile, statuses) if analyzed(n)]


def _passport(f):
    """Кому и каким каналом написано сообщение референсеру и кто написал версию (source: edit — правка,
    own — своё, нет — модель), по какому шаблону и когда отправлено — из строки-паспорта файла."""
    m = re.match(r"<!-- (\{.*\}) -->", read_text(f))
    info = json.loads(m.group(1)) if m else {}
    return {k: info[k] for k in ("to", "channel", "goal", "source", "template", "sent", "sent_time") if k in info}


def added_time(path):
    """Время добавления вакансии — для «Истории»: в файле только дата («Сохранено»), время берём у создания
    файла, если день совпадает (файл могли пересоздать позже — тогда времени нет)."""
    st = path.stat()
    created = datetime.fromtimestamp(getattr(st, "st_birthtime", None) or (st.st_ctime if sys.platform == "win32" else st.st_mtime))
    return created.strftime("%H:%M:%S") if created.strftime("%d.%m.%Y") == read_vacancy(path)[1]["saved"][:10] else ""


def rating_history(profile, n, result):
    """Свои оценки вакансии для «Истории». Оценка, поставленная до того, как их стали записывать, — одной записью
    по дате из мои-оценки.md (без времени)."""
    items = funnel.read_ratings(profile, result)
    if items:
        return items
    r = ratings.read_rows(profile).get(n) if profile.ratings.exists() else None
    mine = my_rating(r)
    if not mine["my_date"]:
        return []
    return [{"date": mine["my_date"], "time": "", "score": mine["my_score"], "can": mine["my_can"], "want": mine["my_want"],
             "decision": mine["my_decision"], "reason": mine["my_reason"]}]


def check_facts(profile, path, *groups):
    """«Проверьте: этого нет в резюме» у каждой версии письма, сообщения референсеру и резюме под вакансию:
    числа и названия не из резюме, «о себе» и вакансии (fact_check). Пересчитывается при каждом открытии —
    и после своей правки. Резюме нет — проверки нет."""
    if not profile.resume.exists():
        return
    names = [v.get("to", "") for g in groups for v in g] + [read_prop(profile.results / path.name, REFERRER_PROP)
                                                           if (profile.results / path.name).exists() else ""]
    src = fact_check.source(profile, read_text(path), *names)
    for g in groups:
        for v in g:
            v["unverified"] = src.unverified(v["text"])


def vacancy_details(profile, n):
    path = vacancy_file(profile, n)
    result, letter = profile.results / path.name, profile.letters / path.name
    interview = profile.interview / path.name
    body = lambda f: strip_service(read_text(f)).split("\n---\n", 1)[-1].strip()   # без шапки со ссылками

    def versions(current, history):               # текущее письмо и прежние версии, новые сверху
        out = []
        if current.exists():
            at = datetime.fromtimestamp(current.stat().st_mtime)
            out.append({"text": body(current), "current": True, "key": "", **_passport(current),
                        "when": at.strftime("%d.%m.%Y %H:%M"), "at": at.isoformat(sep=" ", timespec="seconds")})
        for old in history:
            stamp = datetime.strptime(old.stem[:19], "%Y-%m-%d %H-%M-%S")
            out.append({"text": body(old), "current": False, "key": old.stem, **_passport(old), "when": stamp.strftime("%d.%m.%Y %H:%M"),
                        "at": stamp.isoformat(sep=" ")})
        return out

    letters = versions(letter, analysis.letter_history(profile, path.name))
    ref_letters = versions(profile.referrer_letters / path.name, analysis.referrer_history(profile, path.name))
    resume_fits = versions(profile.resume_fits / path.name, analysis.resume_fit_history(profile, path.name))
    check_facts(profile, path, letters, ref_letters, resume_fits)
    # правки и свои тексты — события «Истории»: время — у файла версии
    texts = [{"date": v["at"][:10], "time": v["at"][11:], "kind": kind, "source": v["source"]}
             for kind, vs in (("cover", letters), ("referrer", ref_letters), ("resume", resume_fits))
             for v in vs if v.get("source") in analysis.SOURCES]
    texts += [{"date": v["sent"], "time": v.get("sent_time", ""), "kind": kind, "source": "sent"}   # «Отправлено»
              for kind, vs in (("cover", letters), ("referrer", ref_letters), ("resume", resume_fits)) for v in vs if v.get("sent")]
    shelf = artifacts.listing(profile, result)
    texts += [{"date": e["date"], "time": e["added"][11:] if e["added"][:10] == e["date"] else "", "kind": e["type"],
               "source": "artifact", "title": e["title"]} for e in shelf if e["type"] in ("file", "note")]
    referrer = read_prop(result, REFERRER_PROP) if result.exists() else ""
    criteria = profile.read_criteria() if profile.criteria_file.exists() else ""
    return {"n": n,
            "criteria": criteria, "criteria_changed": criteria_changed(profile, result),
            "model": (read_meta(result) or {}).get("model", "") if result.exists() else "",    # кто оценивал
            "analysis_date": (read_meta(result) or {}).get("date", "") if result.exists() else "",   # когда
            "vacancy": without_saved(strip_service(read_text(path))),
            "analysis": analysis_body(read_text(result)) if result.exists() else "",
            "parsed": parsed_analysis(result),                      # разбор по разделам — карточка рисует его
            "letter": letters[0]["text"] if letters and letters[0]["current"] else "",
            "letters": letters,
            "templates": len(letter_templates.all_templates(profile)),   # один шаблон — его название у версий не пишем
            "ref_letters": ref_letters, "referrer": referrer, "resume_fits": resume_fits,
            "texts": texts,
            "artifacts": shelf,                                     # вкладка «Артефакты»                                         # правки писем и резюме, свои тексты
            "edits": funnel.read_edits(profile, result),           # правки комментария и референсера — для «Истории»
            "analyses": funnel.read_analyses(profile, result),     # итоги разборов
            "ratings": rating_history(profile, n, result),         # свои оценки — «Мои оценки», калибровка
            "added_time": added_time(path),
            "finance": sites.finance_link(read_vacancy(path)[1].get("company", ""), read_text(path)),   # отчётность (ФНС)
            "referrer_candidates": contacts.candidates(profile, read_vacancy(path)[1].get("company", "")),
            "about": company.about(profile, n),                     # «О компании»: агентство, рейтинг hh, прошлые вакансии
            "interview": body(interview) if interview.exists() else "",
            "interview_when": datetime.fromtimestamp(interview.stat().st_mtime).strftime("%d.%m.%Y %H:%M")
                              if interview.exists() else ""}
