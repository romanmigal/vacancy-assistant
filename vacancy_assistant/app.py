"""Окно программы: страница в браузере, которую показывает маленький сервер на этом компьютере.

python3 razbor.py app — сервер слушает только 127.0.0.1 (из сети недоступен) и открывает браузер.
Доступ из домашней сети — по желанию, отдельным сервером с паролем (см. network.py).
Каждый запрос к данным несёт случайный ключ, который сервер вписывает в страницу при запуске:
чужая веб-страница, открытая в том же браузере, не сможет менять статусы или запускать разбор.

Данные — те же файлы профиля, что у командной строки и Obsidian: статусы — в vacancy-status.md,
заметки — в свойстве «заметка» файла разбора. Можно пользоваться и окном, и Obsidian вперемешку.
"""
import base64
import io
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import webbrowser
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import __version__, actual, analysis, answer, artifacts, backup, calibration, cloud, company, contacts, criteria_history, datadir, dupes, fix, funnel, gaps, help, hh, letter_templates, links, mails, market, mask, network, ratings, rss, resume_pdf, salaries, settings, setup, similar, sites, stats, summary, tasks, tune, updates, weekly
from .model import current_model
from .errors import AssistantError
from .hh import phase
from .files import (REFERRER_ID_PROP, REFERRER_PROP, analysis_body, decision_yes, say_decision, numbered_files, read_meta, read_note, read_prop,
                    read_vacancy, set_note, set_prop, strip_service)
from .profile import Profile, default_profile_name, profile_names
from .textio import read_json, read_text, write_json, write_text

WEB = Path(__file__).resolve().parent / "web"
STATIC = re.compile(r"/(?:[a-z-]+\.(?:css|svg)|js/[a-z-]+\.js)")      # только такие имена — никаких «../»
STATIC_TYPES = {".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml"}
PORT = 8765                       # если занят — берём любой свободный


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
            "criteria_changed": criteria_changed(profile, result, meta, current),
            "violations": violations(read_text(result), names) if meta else [],
        })
    like = similar.bonuses(rows, texts) if similar.enabled(profile) else {}   # «Хочу» выше у похожих на отклики
    for r in rows:
        r["want_bonus"], r["want_like"] = like.get(r["n"], {}).get("bonus", 0), like.get(r["n"], {}).get("like", [])
    people = contacts.load(profile)                    # сколько знакомых в компании вакансии — значок в таблице
    by_id = {c["id"]: c for c in people}
    for r in rows:
        r["contacts"] = sum(1 for c in people if contacts.match_level(r["company"], c.get("company", "")) == 2)
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


def analyze_and_write(profile, log, ask):
    """Разбор новых вакансий. Письма сами не пишутся — только кнопкой во вкладке «Письма» карточки."""
    analysis.analyze(profile, log=log, ask=ask, summary=False)


def hh_info(p):
    """Поиск на hh.ru для окна: включён ли («on» / «off» / «ask» — профиль прежней версии ещё не выбрал),
    дата согласия и сколько запросов к hh.ru сделано сегодня из дневного предела."""
    f = p.dir / hh.COUNTER_FILE
    used = read_json(f) if f.exists() else {}
    return {"state": p.hh_state, "consent": (p.config.get("hh_авто") or {}).get("согласие", ""),
            "used": used.get("запросов", 0) if used.get("дата") == date.today().isoformat() else 0,
            "limit": hh.DAY_LIMIT}


# Действия, которым нужна модель: в режиме «Без модели» их кнопки неактивны, а сервер отказывает —
# на случай, если кнопку обошли. Поиск и добавление вакансий работают — вакансии сохраняются без разбора
NEEDS_MODEL = {"analyze", "refresh", "tune", "rescore_all", "letter", "referrer_letter", "interview",
               "interview_questions", "resume_fit", "fix_suggest", "fix_check", "fix_recheck", "market_advice",
               "market_recheck"}
NO_MODEL_ERROR = "Нужна модель — включите локальную или облачную в «Параметры → Настройки»."


def make_work(profile, action, data, fetch_page=None, ask=None):
    """Задача для кнопки окна. fetch_page и ask — подмена hh.ru и модели в тестах."""
    if action in NEEDS_MODEL and profile.no_model:
        raise AssistantError(NO_MODEL_ERROR)
    hh_kw = {"fetch_page": fetch_page} if fetch_page else {}
    if action == "update":
        feeds = rss.enabled(profile)
        if not feeds:
            hh.require_auto(profile)            # поиск на hh.ru выключен и лент нет — отказ сразу, без обращения к сети
        limit = int(data.get("limit") or 0) or None
        def work(log):
            got = []
            if not profile.hh_auto:
                log("Поиск на hh.ru выключен — читаю только ленты вакансий.")
            elif profile.searches.exists() and hh.read_queries(profile):
                got = hh.search(profile, log, limit=limit, **hh_kw) or []
            else:
                log("Поисковых запросов нет (поиски.txt) — только разбор.")
            left = rss.leftover(limit or profile.search_limit, len(got))   # лимит общий: ленты — остаток после hh.ru
            if feeds and left == 0:
                log("Лимит вакансий за поиск набран на hh.ru — ленты Хабр Карьеры и GeekJob прочитаю при следующем поиске.")
            elif feeds:                         # RSS Хабр Карьеры и GeekJob
                rss.search(profile, log, ask=ask, limit=left, **hh_kw)
            analyze_and_write(profile, log, ask)
        return "Найти новые вакансии", work
    if action == "add":                         # ссылки hh.ru и любых других сайтов
        links = data.get("links", "")
        hh_ids, other = sites.split_links(links)
        if not hh_ids and not other:
            raise AssistantError("Не нашёл ссылок на вакансии.")
        if not other:
            hh.require_auto(profile)            # только ссылки hh.ru, а поиск на hh выключен — отказ без сети
        def work(log):                          # разбираются только добавленные: остальное — дело пачки
            added = sites.add_any(profile, links, log, fetch_page, ask)
            if added:
                analysis.analyze(profile, log=log, ask=ask, summary=False, only=[f.name for f in added])
        return "Добавить вакансию по ссылке", work
    if action == "add_text":                    # вакансия, вставленная текстом (сайт не отдаёт страницу)
        def work(log):
            added = sites.add_text(profile, data.get("text", ""), data.get("link", ""), log, ask)
            if added:                                   # None — та же вакансия уже есть
                analysis.analyze(profile, log=log, ask=ask, summary=False, only=[added.name])
        if len((data.get("text") or "").strip()) < 100:
            raise AssistantError("Вставьте текст вакансии целиком — название, обязанности, требования.")
        return "Добавить вакансию из текста", work
    if action == "add_page":                    # страница вакансии, сохранённая в браузере, — без сети
        page, name = data.get("page") or "", data.get("name") or ""
        if len(page) < 500 or "<" not in page:
            raise AssistantError("Это не страница вакансии: загрузите файл .html, сохранённый в браузере (⌘S или Ctrl+S).")
        def work(log):
            added = sites.add_saved(profile, page, name, log, ask)
            if added:
                analysis.analyze(profile, log=log, ask=ask, summary=False, only=[added.name])
        return "Добавить вакансию из сохранённой страницы", work
    if action == "analyze":
        return "Разбор новых вакансий", lambda log: analyze_and_write(profile, log, ask)
    if action == "refresh":                     # после правки профиля: переоценка и новые версии писем по статусам
        reanalyze, reletters = set(data.get("reanalyze") or []), set(data.get("reletters") or [])
        if not reanalyze and not reletters:
            raise AssistantError("Выберите, что сделать.")

        def targets():
            names = with_status(profile, reanalyze)
            if data.get("only_short"):              # сменили оценку на одну ступень: только с одной быстрой оценкой
                names = [n for n in names if (profile.results / n).exists()
                         and (read_meta(profile.results / n) or {}).get("stage") == "short"]
            return names

        def work(log):
            if reanalyze:
                analysis.analyze(profile, log=log, ask=ask, summary=False, only=targets())
            if reletters:
                analysis.write_letters(profile, log=log, ask=ask, summary=False, only=with_status(profile, reletters))
        return ("Переоценка вакансий" if reanalyze else "Новые версии писем"), work
    if action == "tune":                        # калибровка: автонастройка критериев по своим оценкам
        rounds = max(1, min(5, int(data.get("rounds") or 3)))
        only = calibration.picked(profile)

        def work(log):
            phase(log, "Автонастройка критериев")
            tune.tune(profile, rounds, log=log, ask=ask, only=only)
            # Состав последней калибровки: значит, калибровку уже делали — больше не предлагать
            write_json(profile.dir / calibration.FILE, {**calibration.read(profile), "last": sorted(only)})
        return "Автонастройка критериев", work
    if action == "fix_suggest":                 # окно «Мои оценки»: правка критериев и проверка на вакансии
        n = int(data["n"])
        if data.get("direction") not in ("up", "down"):
            raise AssistantError("Укажите, выше или ниже должна быть оценка.")

        def work(log):
            phase(log, "Правка критериев по вакансии")
            fix.suggest(profile, n, data, log, ask=ask)
        return "Правка критериев по вакансии", work
    if action == "fix_check":                   # та же правка — на уже оценённых вакансиях: не сломали ли остальное
        n = int(data["n"])

        def work(log):
            phase(log, "Проверка правки на оценённых вакансиях")
            fix.check_reference(profile, n, log, ask=ask)
        return "Проверка правки критериев", work
    if action == "fix_recheck":                 # свои правки критериев, резюме, «о себе» — и пересчёт этой вакансии
        n = int(data["n"])

        def work(log):
            phase(log, "Пересчёт вакансии после правки")
            fix.recheck(profile, n, data, log, ask=ask)
        return "Пересчёт вакансии после правки", work
    if action == "market_recheck":              # «Резюме против рынка»: правка резюме и «о себе» — и пересчёт вакансий
        ns = [int(n) for n in data.get("ns") or []]
        if not ns:
            raise AssistantError("Отметьте вакансии, которые пересчитать.")

        def work(log):
            phase(log, f"Пересчёт {len(ns)} {'вакансии' if len(ns) == 1 else 'вакансий'} после правки")
            gaps.recheck(profile, ns, data, log, ask=ask)
        return "Резюме против рынка: пересчёт", work
    if action == "market_advice":               # «Резюме против рынка»: что дописать и что нарастить
        def work(log):
            phase(log, f"Резюме против рынка: что прокачать — моделью {current_model()}")
            market.write_advice(profile, vacancy_rows(profile), log, ask or analysis.ask_model, data.get("since"))
        return "Резюме против рынка: формулировки", work
    if action == "rescore_all":                 # кнопка ↻ в шапке: устаревшие или все разобранные в выбранных разделах
        statuses = set(data.get("statuses") or [])
        if data.get("mode") == "all":
            names = analyzed_with_status(profile, statuses)
            if not names:
                raise AssistantError("В выбранных разделах нет разобранных вакансий.")
        else:
            names = changed_with_status(profile, statuses)
            if not names:
                raise AssistantError("В выбранных разделах нет вакансий, оценённых по прежним критериям, — "
                                     "выберите «Все вакансии в выбранных разделах».")

        def work(log):
            phase(log, f"Полный разбор по новым данным моделью {current_model()}")
            log(f"Вакансий: {len(names)}, около минуты на каждую")
            for i, name in enumerate(names, 1):
                path = profile.vacancies / name
                log(f"[{i}/{len(names)}] Разбираю: {read_vacancy(path)[1]['title']}")
                try:
                    _, result, sec = analysis.full_analysis(profile, path, log=log, ask=ask)
                    log(f"      оценка {result['score']}/10, откликаться: {say_decision(result['decision'])} ({sec} с)")
                except AssistantError as e:
                    if type(e).__name__ == "Stopped":            # «Остановить» — не ошибка разбора
                        raise
                    log(f"      {e}")
        return "Пересчёт оценок по новым данным", work
    if action == "letter":                      # кнопка в карточке: письмо для одной вакансии при любой оценке
        result = vacancy_file(profile, data.get("n", 0), profile.results, "Письмо можно написать после разбора вакансии.")

        def work(log):
            if (read_meta(result) or {}).get("stage") in ("short", analysis.NO_MODEL):    # письму нужны сильные стороны из полного разбора
                phase(log, f"Полный разбор моделью {current_model()} — нужен для письма")
                analysis.full_analysis(profile, profile.vacancies / result.name, log=log, ask=ask)
            phase(log, f"Пишу {'новую версию письма' if (profile.letters / result.name).exists() else 'сопроводительное письмо'} "
                       f"моделью {current_model()}")
            log(f"Пишу письмо: {read_meta(result)['title']}")
            analysis.write_letter(profile, result, log=log, ask=ask, example=example, template=tpl["id"])
        tpl = letter_templates.get(profile, int(data["template"]) if data.get("template") else None)
        example = (data.get("example") or "").strip() or None     # шаблон, поправленный для этого письма
        if example and data.get("save_example") and example != tpl["text"]:     # …и сохранённый в шаблон
            letter_templates.save(profile, tpl["id"], tpl["name"], example, source="правка перед письмом")
        return "Сопроводительное письмо", work
    if action == "referrer_letter":             # вкладка «Письма»: сообщение референсеру вакансии
        result = vacancy_file(profile, data.get("n", 0), profile.results, "Написать референсеру можно после разбора вакансии.")
        to = read_prop(result, REFERRER_PROP)
        if not to:
            raise AssistantError("Сначала укажите референсера — в поле «Референсер» карточки: из контактов или вручную.")
        person = next((c for c in contacts.load(profile) if c["id"] == read_prop(result, REFERRER_ID_PROP)), {})
        about = "; ".join(x for x in (person.get("note"), f"статус переписки: {dict(contacts.STATUSES)[person['status']]}"
                                      if person.get("status") else "") if x)

        def work(log):
            if (read_meta(result) or {}).get("stage") in ("short", analysis.NO_MODEL):    # сильные стороны — из полного разбора
                phase(log, f"Полный разбор моделью {current_model()} — нужен для сообщения")
                analysis.full_analysis(profile, profile.vacancies / result.name, log=log, ask=ask)
            phase(log, f"Пишу сообщение референсеру моделью {current_model()}")
            log(f"Кому: {to}")
            analysis.write_referrer_letter(profile, result, to, about, data.get("channel", "telegram"), data.get("goal", "pass"),
                                           data.get("extra", ""), log=log, ask=ask)
        return "Сообщение референсеру", work
    if action == "refresh_card":                # кнопка в карточке: текст вакансии и полный разбор заново
        path = vacancy_file(profile, data.get("n", 0))

        def work(log):
            phase(log, "Разбираю вакансию заново по текущим настройкам")
            link, seen = read_vacancy(path)[1]["link"], {}
            if "hh.ru/" in link:                                          # hh.ru: только актуальность, текст прежний
                seen["actual"] = actual.check_hh(profile, link, fetch_page or hh.fetch, log,
                                                 on_page=lambda page, get: (company.from_page(profile, path, page, get, log),
                                                                            hh.set_posted(path, hh.posted(page))))
            else:                                                         # другой сайт: перечитать страницу
                sites.refresh(profile, path, log, fetch_page or sites.fetch, ask, seen)
            state = seen.get("actual")
            if state:
                log("Вакансия на сайте закрыта." if state == actual.GONE else "Вакансия на сайте открыта.")
            actual.record(profile.results / path.name, state)             # разбор уже есть — сразу: модель может сбиться
            if profile.no_model:                                          # «Без модели»: только актуальность и текст
                actual.record(analysis.save_unanalyzed(profile, path), state)
                log("Модель не используется — разбор не делаю.")
                return
            phase(log, f"Полный разбор моделью {current_model()}")          # всегда полный — при любой оценке
            log(f"Разбираю: {read_vacancy(path)[1]['title']}")
            target, result, sec = analysis.full_analysis(profile, path, log=log, ask=ask)
            log(f"      оценка {result['score']}/10, откликаться: {say_decision(result['decision'])} ({sec} с)")
            if not actual.read(target)["checked"]:
                actual.record(target, state)                              # разбора не было — пишем в новый
        return "Разобрать заново", work
    if action == "interview":                   # кнопка в карточке: истории STAR к собеседованию
        result = vacancy_file(profile, data.get("n", 0), profile.results,
                              "Подготовиться к интервью можно после разбора вакансии.")

        def work(log):
            if (read_meta(result) or {}).get("stage") in ("short", analysis.NO_MODEL):    # нужны требования и пробелы из полного разбора
                phase(log, f"Полный разбор моделью {current_model()} — нужен для подготовки")
                analysis.full_analysis(profile, profile.vacancies / result.name, log=log, ask=ask)
            phase(log, f"Готовлю истории к интервью моделью {current_model()}")
            log(f"Подбираю истории из резюме под требования: {read_meta(result)['title']} (1–3 минуты)")
            analysis.write_interview(profile, result, log=log, ask=ask)
        return "Подготовка к интервью", work
    if action == "resume_fit":                  # кнопка в карточке: резюме под вакансию
        result = vacancy_file(profile, data.get("n", 0), profile.results,
                              "Подогнать резюме можно после разбора вакансии.")

        def work(log):
            if (read_meta(result) or {}).get("stage") in ("short", analysis.NO_MODEL):    # нужны сильные стороны из полного разбора
                phase(log, f"Полный разбор моделью {current_model()} — нужен для резюме")
                analysis.full_analysis(profile, profile.vacancies / result.name, log=log, ask=ask)
            phase(log, f"Подгоняю резюме под вакансию моделью {current_model()}")
            log(f"Что поднять, «Обо мне» и навыки: {read_meta(result)['title']} (1–2 минуты)")
            analysis.write_resume_fit(profile, result, log=log, ask=ask)
        return "Резюме под вакансию", work
    if action == "interview_questions":         # кнопка в карточке: вопросы работодателю к готовой подготовке
        result = vacancy_file(profile, data.get("n", 0), profile.results,
                              "Вопросы работодателю можно подготовить после разбора вакансии.")

        def work(log):
            if (read_meta(result) or {}).get("stage") in ("short", analysis.NO_MODEL):    # нужны пробелы и неясности из полного разбора
                phase(log, f"Полный разбор моделью {current_model()} — нужен для вопросов")
                analysis.full_analysis(profile, profile.vacancies / result.name, log=log, ask=ask)
            phase(log, f"Готовлю вопросы работодателю моделью {current_model()}")
            log(f"Вопросы по пробелам и неясностям разбора: {read_meta(result)['title']} (до минуты)")
            analysis.write_questions(profile, result, log=log, ask=ask)
        return "Вопросы работодателю", work
    raise AssistantError(f"Неизвестное действие «{action}»")


# Одиночные задачи — для одной вакансии, по кнопке: пачка пропускает их вперёд. Остальные — пачки.
SINGLE = {"add", "add_text", "add_page", "letter", "referrer_letter", "refresh_card", "interview", "interview_questions", "resume_fit",
          "fix_suggest", "fix_recheck", "market_advice"}


class Forbidden(AssistantError):
    """Запрос, который с этого устройства делать нельзя (ответ 403)."""


class Route:
    def __init__(self, fn, method, profile, writes, idle, local):
        self.fn, self.method, self.profile, self.writes, self.idle, self.local = fn, method, profile, writes, idle, local


ROUTES = {}


def route(path, method="GET", profile=True, writes=False, idle=None, local=False):
    """Регистрирует обработчик адреса окна. method: GET — только чтение (можно и POST), POST — только POST,
    ANY — и то и другое. profile — нужен профиль из параметра profile; writes — под блокировкой записи;
    idle — текст ошибки, если идёт задача; local — только с этого компьютера (не из домашней сети)."""
    def register(fn):
        ROUTES[path] = Route(fn, method, profile, writes, idle, local)
        return fn
    return register


class App:
    def __init__(self, profiles_dir=None, fetch_page=None, ask=None, check=None):
        self.profiles_dir = profiles_dir
        self.check = check or setup.check_computer           # в тестах — подмена
        self.fetch_page, self.ask = fetch_page, ask
        self.fetch_rates = None                              # курсы ЦБ; в тестах — подмена
        self.fetch_latest = updates.fetch_latest             # проверка обновлений; в тестах — подмена
        self.pick_folder = datadir.pick                      # системное окно выбора папки; в тестах — подмена
        self.trash = None                                    # в Корзину системы; в тестах — своя папка
        self.token = secrets.token_urlsafe(24)
        self.queues = tasks.Queues()
        self.write_lock = threading.Lock()
        self.exported = {}                                   # профиль → строки таблицы при последней выгрузке сводки
        self.lan, self.lan_error, self.gate = None, "", network.Gate()
        self.lan_port = network.PORT                         # в тестах — 0 (любой свободный)

    @property
    def config_dir(self):
        return Path(self.profiles_dir) if self.profiles_dir else settings.profiles_dir()

    def start_lan(self):
        """Сервер для домашней сети — если доступ включён в настройках."""
        self.stop_lan()
        port = self.lan_port
        if not network.load(self.config_dir).get("enabled"):
            return
        try:
            self.lan = Server(("0.0.0.0", port), handler_for(self, remote=True))
        except OSError as e:
            self.lan_error = f"Не удалось открыть порт {port}: {e}"
            return
        threading.Thread(target=self.lan.serve_forever, daemon=True).start()

    def stop_lan(self):
        if self.lan:
            self.lan.shutdown()
            self.lan.server_close()
        self.lan, self.lan_error = None, ""
        self.gate.clear()                                     # выключили или сменили пароль — всем войти заново

    def network_state(self):
        cfg = network.load(self.config_dir)
        port = self.lan.server_address[1] if self.lan else self.lan_port or network.PORT
        return {"enabled": bool(cfg.get("enabled")), "has_password": bool(cfg.get("hash")),
                "running": bool(self.lan), "error": self.lan_error, "urls": network.addresses(port)}

    def export(self, p, rows):
        """Сводка.md для Obsidian — заново, как только изменилась левая панель окна."""
        key = json.dumps(rows, ensure_ascii=False, sort_keys=True, default=str)
        if self.exported.get(p.name) != key:
            with self.write_lock:
                summary.write_summary(p, log=lambda *_: None)
            self.exported[p.name] = key

    def profile(self, name):
        name = name or default_profile_name(self.profiles_dir)
        if not name or name not in profile_names(self.profiles_dir):       # только папки профилей, никаких «../»
            raise AssistantError(f"Нет профиля «{name}»")
        return Profile(name, self.profiles_dir)

    def handle(self, method, path, query, data, remote=False):
        """Запрос окна → функция из таблицы ROUTES. Общие проверки — здесь, по пометкам маршрута:
        метод, «только на этом компьютере», «нельзя во время задачи», блокировка записи, профиль."""
        r = ROUTES.get(path)
        if not r or (r.method == "POST" and method != "POST"):
            raise AssistantError("Нет такого адреса")
        if remote and r.local:
            raise Forbidden("Это можно сделать только на основном компьютере.")
        args = {k: v[0] for k, v in query.items()} if method == "GET" else data
        p = self.profile(args.get("profile")) if r.profile else None
        if r.idle and p and self.queues.busy(p.name):          # мешают только задачи своего профиля
            raise AssistantError(r.idle)
        cloud.use(p)                                   # модель — та, что выбрана в профиле запроса
        if r.writes:
            with self.write_lock:
                return r.fn(self, p, args)
        return r.fn(self, p, args)

    # --- состояние окна и задачи

    @route("/api/state", profile=False)
    def api_state(self, p, a):
        if not profile_names(self.profiles_dir):             # первый запуск: профилей нет — окно откроет мастер
            return {"profiles": [], "profile": None, "name": "", "model": current_model(), "version": __version__,
                    "contact": settings.CONTACT_EMAIL, "source": settings.SOURCE_URL, "statuses": summary.STATUSES, "rows": [], "tasks": self.queues.snapshot(None)}
        p = self.profile(a.get("profile"))
        cloud.use(p)
        rows = vacancy_rows(p)
        self.export(p, rows)
        return {"profiles": profile_names(self.profiles_dir), "profile": p.name,
                "name": p.display_name, "model": "не используется" if p.no_model else current_model(), "version": __version__,
                "contact": settings.CONTACT_EMAIL, "source": settings.SOURCE_URL, "no_model": p.no_model, "unanalyzed": sum(1 for r in rows if r["stage"] in ("", analysis.NO_MODEL)),
                "two_stage": p.two_stage,
                "two_stage_setting": p.two_stage_setting, "llm_pages": p.llm_pages, "rss": rss.enabled(p), "cloud": cloud.active(p),
                "search_days": p.search_days, "search_limit": p.search_limit,
                "calibration_need": calibration.NEED, "calibrated": "last" in calibration.read(p),
                "statuses": summary.statuses(p), "custom_statuses": [k for k, _ in p.custom_statuses], "status_colors": p.status_colors, "rows": rows, "tasks": self.queues.snapshot(p.name),
                "stages": funnel.STAGES, "columns": p.columns, "hh": hh_info(p),
                "want_similar": similar.enabled(p)}

    @route("/api/jobs", profile=False)
    def api_jobs(self, p, a):
        """Обе очереди: свои задачи — целиком, с логом; чужие — только «задача другого профиля»."""
        return {"tasks": self.queues.snapshot(a.get("profile"))}

    @route("/api/stop", "POST", profile=False)
    def api_stop(self, p, a):
        """Остановить свою задачу или убрать её из очереди (чужую — нельзя)."""
        self.queues.stop(int(a.get("task_id") or 0), a.get("profile"))
        return {"tasks": self.queues.snapshot(a.get("profile"))}

    @route("/api/quit", "POST", profile=False, local=True)    # у установленной программы нет консоли
    def api_quit(self, p, a):
        self.queues.stop_all()
        if getattr(self, "server", None):
            threading.Thread(target=self.server.shutdown, daemon=True).start()
        return {"ok": True}

    @route("/api/network", "ANY", profile=False, local=True, writes=True)   # доступ из домашней сети
    def api_network(self, p, a):
        if "enabled" in a:
            network.save(self.config_dir, a.get("enabled"), a.get("password"))
            self.start_lan()
        return self.network_state()

    # --- папка с данными: сменить, подхватить профили из другой папки

    @route("/api/datadir", profile=False, local=True)
    def api_datadir(self, p, a):
        home = self.config_dir.parent
        return {"home": str(home), "profiles": profile_names(self.profiles_dir), "copies": str(backup.copies_dir(self.config_dir))}

    @route("/api/datadir/pick", "POST", profile=False, local=True)   # окно выбора папки на этом компьютере
    def api_datadir_pick(self, p, a):
        path = self.pick_folder()
        return {"picked": bool(path), **(datadir.inspect(path) if path else {})}

    @route("/api/datadir/inspect", "POST", profile=False, local=True)   # путь, введённый вручную
    def api_datadir_inspect(self, p, a):
        return datadir.inspect(a.get("path"))

    @route("/api/datadir/set", "POST", profile=False, local=True, writes=True)
    def api_datadir_set(self, p, a):
        """Работать с другой папкой данных: профили в ней подхватываются, нет — окно предложит создать.
        Прежняя папка остаётся как есть — ничего не переносится и не удаляется."""
        if self.queues.running():
            raise AssistantError("Идут задачи — дождитесь их или остановите, потом меняйте папку.")
        info = datadir.inspect(a.get("path"))
        if info["problem"]:
            raise AssistantError(info["problem"])
        home = Path(info["home"])
        (home / datadir.PROFILES).mkdir(exist_ok=True)
        if self.profiles_dir:                                # в тестах — своя папка, файл настроек пользователя не трогаем
            self.profiles_dir = home / datadir.PROFILES
        else:
            datadir.remember(home)
            os.environ["VACANCY_ASSISTANT_HOME"] = str(home)   # установленная программа ставит её при запуске
        self.exported.clear()
        self.start_lan()                                     # доступ из сети — по настройке новой папки
        return self.api_datadir(p, a)

    @route("/api/updates", "ANY", profile=False, local=True, writes=True)  # проверка обновлений: раз в день
    def api_updates(self, p, a):
        if "enabled" in a:
            updates.set_enabled(self.config_dir, a.get("enabled"))
        out = updates.state(self.config_dir, self.fetch_latest, force=bool(a.get("check")))   # «Проверить обновления»
        return {**out, "mac_install": settings.MAC_INSTALL} if sys.platform == "darwin" else out   # плашка: обновить командой

    @route("/api/cloud", "ANY", profile=False, local=True, writes=True)    # облачная модель GigaChat
    def api_cloud(self, p, a):
        """Ключ GigaChat — общий для компьютера; выбор модели — у профиля из параметра profile.
        Без профиля (мастер, профиля ещё нет) — только сохранить и проверить ключ."""
        p = self.profile(a["profile"]) if a.get("profile") else None
        if p and "enabled" in a and bool(a.get("enabled")) != p.use_cloud and self.queues.busy(p.name):
            raise AssistantError("У профиля есть задачи в очереди — сменить модель можно, когда они закончатся.")
        if "enabled" in a:
            return cloud.save(self.config_dir, a.get("enabled"), a.get("auth_key"), a.get("scope"),
                              a.get("model"), a.get("consent"), profile=p)
        return cloud.public(self.config_dir, p)

    @route("/api/mask", local=True)                    # что скрывается от GigaChat и как модель видит резюме
    def api_mask(self, p, a):
        firms = a.get("companies")
        return mask.preview(p, None if firms is None else firms in ("1", "true"))

    @route("/api/cloud/check", "POST", profile=False, local=True)
    def api_cloud_check(self, p, a):
        """Проверить ключ, не сохраняя: новый ключ из формы или уже сохранённый."""
        cfg = {**cloud.load(self.config_dir), **{k: v for k, v in a.items() if k in ("auth_key", "scope", "model") and v}}
        if not cfg.get("auth_key"):
            raise AssistantError("Вставьте ключ авторизации GigaChat.")
        return cloud.check(cfg)

    @route("/api/run", "POST")
    def api_run(self, p, a):
        action = a.get("action")
        title, work = make_work(p, action, a, self.fetch_page, self.ask)
        n = int(a["n"]) if action in SINGLE and a.get("n") else None
        task = self.queues.add("single" if action in SINGLE else "batch", f"{title} · {p.display_name}", work, p, action, n)
        return {"task_id": task.id, "position": self.queues.position(task), "task": self.queues.view(task, p.name)}

    # --- вакансии

    @route("/api/vacancy")
    def api_vacancy(self, p, a):
        return vacancy_details(p, int(a["n"]))

    @route("/api/status", "POST", writes=True)
    def api_status(self, p, a):
        value = a.get("value")
        if value not in dict(summary.statuses(p)):
            raise AssistantError(f"Неизвестный статус {value}")
        n = int(a["n"])
        if summary.read_statuses(p).get(f"s{n}", "new") != value:
            summary.set_status(p, f"s{n}", value)
            path = p.results / vacancy_file(p, n).name
            funnel.record_status(path, value, profile=p)       # история — во вкладке «История» карточки
        return {"ok": True}

    @route("/api/statuses", "POST", writes=True)
    def api_statuses(self, p, a):
        """Свои статусы: add — name, color; rename — key, name; color — key, color; order — keys; delete — key, move_to (куда перенести вакансии)."""
        do, moved = a.get("do"), 0
        if do == "add":
            summary.add_status(p, a.get("name"), a.get("color"))
        elif do == "rename":
            summary.rename_status(p, a.get("key"), a.get("name"))
        elif do == "color":
            summary.color_status(p, a.get("key"), a.get("color"))
        elif do == "order":
            summary.order_statuses(p, a.get("keys"))
        elif do == "delete":
            moved = summary.delete_status(p, a.get("key"), a.get("move_to") or "new")
        else:
            raise AssistantError(f"Неизвестное действие {do}")
        return {"statuses": summary.statuses(p), "custom_statuses": [k for k, _ in p.custom_statuses], "status_colors": p.status_colors, "moved": moved}

    @route("/api/recheck")
    def api_recheck(self, p, a):
        """Отсеянные по названию за 14 дней, которые проходят отбор по нынешним правилам."""
        return {"items": hh.recheck_filtered(p), "hh_auto": p.hh_auto}

    @route("/api/mails", "POST", writes=True)
    def api_mails(self, p, a):
        """Письма hh (.eml, base64) → вакансии из них. На hh.ru программа не ходит; из ссылок — только номера."""
        letters = [(f.get("name", "письмо"), base64.b64decode(f.get("data", ""))) for f in a.get("files", [])]
        return {**mails.inbox(p, letters), "hh_auto": p.hh_auto}

    @route("/api/company/agency", "POST", writes=True)
    def api_company_agency(self, p, a):
        """Ваша пометка «агентство / не агентство» для компании вакансии; null — снять пометку."""
        company.set_mark(p, read_vacancy(vacancy_file(p, a["n"]))[1].get("company", ""), a.get("agency"))
        return {"ok": True}

    @route("/api/companies")                           # раздел «Компании»: компании по вакансиям профиля
    def api_companies(self, p, a):
        return company.companies(p, vacancy_rows(p))

    @route("/api/dupe", "POST", writes=True)
    def api_dupe(self, p, a):
        """Пометка «Возможно, дубль»: merge — ссылки этой вакансии дописать к той и убрать эту в Корзину;
        apart — это разные вакансии, пометку снять."""
        n = int(a["n"])
        path = vacancy_file(p, n)
        if a.get("action") == "apart":
            dupes.clear_maybe(path)
            return {"ok": True, "n": n}
        info = read_vacancy(path)[1]
        if not info["maybe"].isdigit():
            raise AssistantError("У этой вакансии нет пометки «Возможно, дубль».")
        into = vacancy_file(p, int(info["maybe"]), missing="Вакансии, с которой склеить, уже нет в списке — нажмите «Это разные».")
        for url in [info["link"]] + dupes.more_links(read_text(path)):
            if url.startswith("http"):
                dupes.add_link(into, url)
        for folder in (p.results, p.letters, p.referrer_letters, p.interview, p.resume_fits, p.vacancies):
            if (folder / path.name).exists():
                (self.trash or backup.move_to_trash)(folder / path.name)
        return {"ok": True, "n": int(info["maybe"])}

    @route("/api/flag", "POST", writes=True)
    def api_flag(self, p, a):
        n = int(a["n"])
        vacancy_file(p, n)
        summary.set_flag(p, n, bool(a.get("on")))
        return {"ok": True}

    @route("/api/funnel/stage", "POST", writes=True)
    def api_funnel_stage(self, p, a):
        """Этап отклика с датой. Интервью — раздел «Интервью» сам; отказ — окно предложит Архив."""
        n = int(a["n"])
        path = vacancy_file(p, n, p.results, "Этап можно отметить после разбора вакансии.")
        status = summary.read_statuses(p).get(f"s{n}", "new")
        f, section, archive = funnel.set_stage(path, a.get("stage", ""), funnel.parse_date(a.get("date")), status)
        if section:
            summary.set_status(p, f"s{n}", section)
            funnel.record_status(path, section)
            f = funnel.read(path)
        return {"funnel": f, "status": section or status, "archive": archive}

    @route("/api/note", "POST", writes=True)
    def api_note(self, p, a):
        result = vacancy_file(p, a["n"], p.results, "Комментарий можно оставить после разбора вакансии.")
        if read_note(result) != " ".join(a.get("text", "").split()):
            funnel.record_edit(p, result, "comment", a.get("text", ""), read_note(result))   # для вкладки «История»
        set_note(result, a.get("text", ""))
        return {"ok": True, "updated": funnel.updated(funnel.read(result), funnel.read_edits(p, result))}

    # --- контакты: трекер знакомых и кандидаты в референсеры

    @route("/api/contacts")
    def api_contacts(self, p, a):
        return {"contacts": contacts.public(contacts.load(p), vacancy_rows(p)), "statuses": contacts.STATUSES}

    @route("/api/contacts/save", "POST", writes=True)
    def api_contacts_save(self, p, a):
        cid = contacts.upsert(p, a.get("contact") or {})
        item = next(c for c in contacts.load(p) if c["id"] == cid)
        for result in p.results.glob("*.md"):           # поправили имя или должность — и у вакансий, где он референсер
            if read_prop(result, REFERRER_ID_PROP) == cid and read_prop(result, REFERRER_PROP) != contacts.referrer_text(item):
                set_prop(result, REFERRER_PROP, contacts.referrer_text(item))
        return {"id": cid}

    @route("/api/contacts/delete", "POST", writes=True)
    def api_contacts_delete(self, p, a):
        contacts.delete(p, a.get("id", ""))
        return {"ok": True}

    @route("/api/contacts/import", "POST", writes=True)
    def api_contacts_import(self, p, a):
        return contacts.import_linkedin(p, base64.b64decode(a.get("data", "")), a.get("name", ""))

    # --- где искать вакансии: общий список и свои ссылки профиля

    @route("/api/market", "POST", writes=True)         # «Резюме против рынка»: отклики и расхождения с since, без модели
    def api_market(self, p, a):
        rep = market.report(p, vacancy_rows(p), a.get("since") or None)
        market.remember(p, rep)
        return rep

    @route("/api/market/undo", "POST", writes=True, idle="Идёт задача — верните, когда она закончится.")
    def api_market_undo(self, p, a):
        gaps.undo(p)
        return {"ok": True}

    @route("/api/stats")                               # раздел «Статистика»: шаг — day, week, month
    def api_stats(self, p, a):
        return stats.compute(vacancy_rows(p), a.get("step", "week"), status_names=summary.statuses(p))

    @route("/api/weekly")                              # «Итоги недели»: week — last (прошлая) или this
    def api_weekly(self, p, a):
        rep = weekly.compute(p, vacancy_rows(p), a.get("week", "last"))
        return {**rep, "markdown": weekly.markdown(rep)}

    @route("/api/salaries")                            # окно «Зарплаты»: вилки из вакансий профиля, планка — из анкеты
    def api_salaries(self, p, a):
        planka = int(re.sub(r"\D", "", str(setup.answers_from_profile(p).get("salary") or "")) or 0)
        return salaries.report(p, self.config_dir, planka, **({"fetch": self.fetch_rates} if self.fetch_rates else {}))

    @route("/api/links")
    def api_links(self, p, a):
        return links.for_profile(p)

    @route("/api/links/favorites")
    def api_links_favorites(self, p, a):
        return {"favorites": links.favorites(p)}

    @route("/api/links/save", "POST", writes=True)
    def api_links_save(self, p, a):
        if a.get("do") == "delete":
            return {"own": links.delete(p, a.get("id", ""))}
        if a.get("do") == "favorite":                 # любимые сайты — список в шапке окна
            return {"favorites": links.set_favorite(p, a.get("url", ""), bool(a.get("on")))}
        return {"own": links.add(p, a.get("name", ""), a.get("url", ""), a.get("about", ""))}

    @route("/api/letter/example")                       # ?template=2 — текст шаблона; без него — по умолчанию
    def api_letter_example(self, p, a):
        return letter_templates.get(p, int(a["template"]) if a.get("template") else None)

    @route("/api/letter/templates")                     # шаблоны сопроводительного письма
    def api_letter_templates(self, p, a):
        return {"templates": letter_templates.all_templates(p), "max": letter_templates.MAX}

    @route("/api/letter/templates/save", "POST", writes=True)
    def api_letter_templates_save(self, p, a):
        tid = int(a["id"]) if a.get("id") else None
        if a.get("do") == "delete":
            letter_templates.delete(p, tid, self.trash or backup.move_to_trash)
        elif a.get("do") == "default":
            letter_templates.set_default(p, tid)
        else:
            tid = letter_templates.save(p, tid, a.get("name", ""), a.get("text", ""), bool(a.get("default")))
        return {"templates": letter_templates.all_templates(p), "max": letter_templates.MAX, "id": tid}

    @route("/api/artifacts/add", "POST", writes=True)  # вкладка «Артефакты»: приложить файл или заметку
    def api_artifacts_add(self, p, a):
        result = vacancy_file(p, a["n"], p.results, "Артефакты — после разбора вакансии.")
        if a.get("do") == "file":
            try:
                data = base64.b64decode(a.get("data", ""), validate=True)
            except ValueError:
                raise AssistantError("Файл не прочитался — выберите его ещё раз.")
            artifacts.add_file(p, result, a.get("name", ""), data, a.get("date") or None, a.get("title", ""))
        else:
            artifacts.add_text(p, result, "note", a.get("title") or artifacts.TYPES["note"], a.get("text", ""), a.get("date") or None)
        return {"artifacts": artifacts.listing(p, result)}

    @route("/api/artifacts/remove", "POST", writes=True)
    def api_artifacts_remove(self, p, a):
        """Убрать из артефактов — в Корзину; у отправленной версии письма или резюме снимается и отметка."""
        result = vacancy_file(p, a["n"], p.results, "Артефакты — после разбора вакансии.")
        entry = artifacts.remove(p, result, a.get("id", ""), self.trash or backup.move_to_trash)
        if entry["type"] in analysis.TEXT_KINDS:
            analysis.unmark_artifact(p, result, entry["id"])
        return {"artifacts": artifacts.listing(p, result)}

    @route("/api/artifacts/open", "POST", local=True)    # приложенный файл — в программе по умолчанию, только здесь
    def api_artifacts_open(self, p, a):
        result = vacancy_file(p, a["n"], p.results, "Артефакты — после разбора вакансии.")
        f = artifacts.file_path(p, result, a.get("id", ""))
        if not f.exists():
            raise AssistantError("Файла нет на месте — его удалили или переместили.")
        if sys.platform == "win32":
            os.startfile(f)                                 # noqa — есть только в Windows
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(f)])
        return {"ok": True}

    @route("/api/letter/sent", "POST", writes=True)     # отметка «Отправлено» у версии письма; date "" — снять
    def api_letter_sent(self, p, a):
        result = vacancy_file(p, a["n"], p.results, "Письма — после разбора вакансии.")
        try:
            sent = analysis.mark_sent(p, result, a.get("kind", ""), a.get("key", ""), a.get("date") or None,
                                      self.trash or backup.move_to_trash)
        except ValueError:
            raise AssistantError("Дата — в виде ГГГГ-ММ-ДД.")
        return {"sent": sent}

    @route("/api/text/save", "POST", writes=True)       # правка письма или резюме под вакансию, своё письмо
    def api_text_save(self, p, a):
        result = vacancy_file(p, a["n"], p.results, "Письма и резюме под вакансию — после разбора вакансии.")
        to = read_prop(result, REFERRER_PROP) if a.get("kind") == "referrer" and a.get("source") == "own" else ""
        analysis.save_text(p, result, a.get("kind", ""), a.get("text", ""), a.get("source", ""), to)
        return {"ok": True}

    @route("/api/referrer", "POST", writes=True)
    def api_referrer(self, p, a):
        result = vacancy_file(p, a["n"], p.results, "Референсера можно указать после разбора вакансии.")
        if read_prop(result, REFERRER_PROP) != " ".join(a.get("text", "").split()):
            funnel.record_edit(p, result, "referrer", a.get("text", ""), read_prop(result, REFERRER_PROP))
        set_prop(result, REFERRER_PROP, a.get("text", ""))
        set_prop(result, REFERRER_ID_PROP, a.get("contact_id") or "")   # вписан вручную — связи с контактом нет
        return {"ok": True}

    # --- профиль, критерии и калибровка

    @route("/api/profile/answers")
    def api_profile_answers(self, p, a):
        return setup.answers_from_profile(p)

    @route("/api/profile/update", "POST", writes=True,
           idle="Идёт задача — сохраните профиль, когда она закончится или остановите её.")
    def api_profile_update(self, p, a):
        return setup.update_profile(p, a.get("answers") or {}, log=lambda *_: None)

    @route("/api/profile/settings", "POST", writes=True)
    def api_profile_settings(self, p, a):
        if "two_stage" in a:
            setup.set_two_stage(p, a["two_stage"])
        if "llm_pages" in a:
            setup.set_llm_pages(p, a["llm_pages"])
        if "hh_auto" in a:                              # поиск на hh.ru: включить — только с согласием на риск
            setup.set_hh_auto(p, a["hh_auto"], a.get("hh_risk"))
        if "search_days" in a:
            setup.set_search_settings(p, a["search_days"], a.get("search_limit"))
        if "no_model" in a:                             # «Без модели» или снова локальная; облачная — через /api/cloud
            if self.queues.busy(p.name):
                raise AssistantError("У профиля есть задачи в очереди — сменить модель можно, когда они закончатся.")
            p.set_model(False, off=bool(a["no_model"]))
        if "rss" in a:                                  # ленты вакансий Хабр Карьеры и GeekJob
            rss.set_enabled(p, a["rss"])
        if "want_similar" in a:                         # «Хочу» выше у похожих на отклики
            similar.set_enabled(p, a["want_similar"])
        if "hide_companies" in a:                       # скрывать прошлых работодателей от GigaChat
            mask.set_hide_companies(p, a["hide_companies"])
        if "columns" in a:                              # колонки таблицы: {order, hidden}
            setup.set_columns(p, (a["columns"] or {}).get("order"), (a["columns"] or {}).get("hidden"))
        return {"ok": True}

    # --- резервные копии профилей (только на этом компьютере: архивы лежат здесь)

    @route("/api/backup", profile=False, local=True)
    def api_backup(self, p, a):
        return {"copies": backup.listing(self.config_dir), "folder": str(backup.copies_dir(self.config_dir))}

    @route("/api/backup/save", "POST", local=True, writes=True)
    def api_backup_save(self, p, a):
        path = backup.make(p)
        return {"file": path.name, **self.api_backup(p, a)}

    @route("/api/backup/export", "POST", local=True, writes=True)
    def api_backup_export(self, p, a):
        """Копия профиля для переноса: сохраняется в «копии/» и отдаётся окну — сохранить куда угодно."""
        path = backup.make(p)
        return {"file": path.name, "data": base64.b64encode(path.read_bytes()).decode("ascii")}

    @route("/api/backup/inspect", "POST", profile=False, local=True)
    def api_backup_inspect(self, p, a):
        """Что в архиве (перенос с другого компьютера): имя, модель, свободное имя папки, есть ли ключ GigaChat."""
        info = backup.inspect(self.config_dir, io.BytesIO(base64.b64decode(a.get("data", ""))))
        return {**info, "has_key": bool(cloud.load(self.config_dir).get("auth_key"))}

    @route("/api/backup/show", "POST", profile=False, local=True)
    def api_backup_show(self, p, a):
        folder = backup.copies_dir(self.config_dir)
        folder.mkdir(parents=True, exist_ok=True)
        backup.reveal(backup.copy_path(self.config_dir, a["file"]) if a.get("file") else folder)
        return {"ok": True}

    @route("/api/backup/restore", "POST", profile=False, local=True, writes=True)
    def api_backup_restore(self, p, a):
        """Копия из списка (file) или выбранный архив (data, base64) → новым профилем или вместо профиля
        из параметра profile (replace) — тогда его задачи не должны идти."""
        into = self.profile(a.get("profile")) if a.get("replace") else None
        if into and self.queues.busy(into.name):
            raise AssistantError("Идут задачи этого профиля — дождитесь их или остановите, потом восстанавливайте.")
        archive = backup.copy_path(self.config_dir, a["file"]) if a.get("file") else io.BytesIO(base64.b64decode(a.get("data", "")))
        name = backup.restore(self.config_dir, archive, into, trash=self.trash, name=a.get("name"))
        self.exported.pop(name, None)
        return {"profile": name, **self.api_backup(p, a)}

    @route("/api/criteria/history", writes=True)       # ?which=letter — версии образца письма
    def api_criteria_history(self, p, a):
        which = a.get("which") or "criteria"
        if which == "criteria":
            criteria_history.import_tune(p, p.dir / tune.TUNE_DIR_NAME)   # версии прошлых автонастроек
            criteria_history.record(p, p.read_criteria(), "текущие критерии")
        else:                                           # which=letter — основной шаблон, letter:2 — второй
            tpl = letter_templates.get(p, int(which[7:]) if ":" in which else 1)
            if tpl["text"]:
                criteria_history.record(p, tpl["text"], "текущий образец", which=letter_templates.which(tpl["id"]))
        return {"versions": criteria_history.versions(p, which)}

    @route("/api/criteria/delete", "POST", writes=True)
    def api_criteria_delete(self, p, a):
        which = a.get("which") or "criteria"
        criteria_history.delete(p, int(a["id"]), which)
        return {"versions": criteria_history.versions(p, which)}

    @route("/api/calibration")
    def api_calibration(self, p, a):
        return calibration.state(p)

    @route("/api/calibration/rate", "POST", writes=True)
    def api_calibration_rate(self, p, a):
        score = ratings.set_rating(p, int(a["n"]), a.get("can"), a.get("want"), a.get("decision"), a.get("reason", ""))
        return {"ok": True, "score": score}

    @route("/api/calibration/select", "POST", writes=True)            # флажок в наборе
    def api_calibration_select(self, p, a):
        if a.get("reset"):
            calibration.reset(p)
        else:
            calibration.choose(p, int(a["n"]), bool(a.get("on")))
        return {"picked": calibration.picked(p)}

    @route("/api/fix")                                  # окно «Мои оценки» в карточке
    def api_fix(self, p, a):
        return fix.view(p, int(a["n"]))

    @route("/api/fix/undo", "POST", writes=True, idle="Идёт задача — верните, когда она закончится.")
    def api_fix_undo(self, p, a):
        fix.undo(p, int(a["n"]))
        return {"ok": True}

    @route("/api/fix/apply", "POST", writes=True, idle="Идёт задача — примените правку, когда она закончится.")
    def api_fix_apply(self, p, a):
        fix.apply(p, int(a["n"]))
        return {"ok": True}

    @route("/api/calibration/apply", "POST", writes=True,
           idle="Идёт задача — примените критерии, когда она закончится.")
    def api_calibration_apply(self, p, a):
        tune.tune_apply(p, log=lambda *_: None)
        return {"ok": True}

    # --- мастер первого запуска: проверка, модель, резюме из PDF, предпросмотр и создание профиля

    @route("/api/setup/check", profile=False)
    def api_setup_check(self, p, a):
        return {**self.check(), "cloud_key": bool(cloud.load(self.config_dir).get("auth_key")),
                "profiles": profile_names(self.profiles_dir),
                "default": default_profile_name(self.profiles_dir), "areas": list(setup.AREAS)}

    @route("/api/setup/area", "ANY", profile=False)
    def api_setup_area(self, p, a):
        area = setup.find_area(a.get("name") or "")
        if not area:
            raise AssistantError("Такого города нет на hh.ru — проверьте название.")
        return area

    @route("/api/setup/examples", profile=False)       # образцы для мастера — вымышленный человек из папки «примеры»
    def api_setup_examples(self, p, a):
        ex = settings.EXAMPLES
        return {k: read_text(ex / f) if (ex / f).exists() else ""
                for k, f in (("resume", "резюме.md"), ("criteria", "критерии.txt"))}

    @route("/api/setup/pull", "POST", profile=False)
    def api_setup_pull(self, p, a):
        task = self.queues.add("service", "Скачивание модели", lambda log: setup.pull_model(log), queue="local")
        return {"task_id": task.id, "task": self.queues.view(task, None)}

    @route("/api/setup/resume", "POST", profile=False)
    def api_setup_resume(self, p, a):
        """Файл резюме (выгрузка hh в TXT, PDF, текст) → текст для поля мастера. Без модели."""
        return {"resume": resume_pdf.file_markdown(base64.b64decode(a.get("data", "")))}

    @route("/api/setup/employers", "POST", profile=False)  # мастер, шаг «Резюме»: кого можно скрыть от GigaChat
    def api_setup_employers(self, p, a):
        return {"past": [v[0] for v in mask.past_employers(a.get("resume") or "")]}

    @route("/api/setup/preview", "POST", profile=False)
    def api_setup_preview(self, p, a):
        answers = a.get("answers") or {}
        field_words, level_words, stop_words = setup.title_filter(answers)
        return {"criteria": setup.build_criteria(answers),
                "title_words": "\n".join(field_words), "level_words": "\n".join(level_words),
                "stop_words": "\n".join(stop_words),
                "queries": setup.lines(answers.get("titles")),
                "letter": setup.letter_sample(answers)}

    @route("/api/setup/create", "POST", profile=False, writes=True)
    def api_setup_create(self, p, a):
        return {"profile": setup.create_profile(a.get("answers") or {}, self.profiles_dir, log=lambda *_: None)}

    def page(self, remote=False):
        html = read_text(WEB / "index.html")
        return (html.replace("{{TOKEN}}", self.token).replace("{{VERSION}}", __version__)
                .replace("{{REMOTE}}", "true" if remote else "false"))


def handler_for(app, remote=False):
    class Handler(BaseHTTPRequestHandler):
        server_version = "VacancyAssistant"

        def log_message(self, *args):            # не засоряем консоль каждой строкой запроса
            pass

        def _send(self, code, body, ctype="application/json; charset=utf-8"):
            raw = body if isinstance(body, bytes) else body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(raw)

        def _local_host(self):
            # Защита от подмены адреса (DNS rebinding): принимаем только обращения к самому компьютеру
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
            return host in ("127.0.0.1", "localhost", "[::1]")

        def _login(self, method):
            """Сервер для домашней сети: только адреса домашней сети и только после пароля."""
            if not network.home_address(self.client_address[0]):
                self._send(403, '{"error": "forbidden"}')
                return False
            if app.gate.valid(self.headers.get("Cookie")):
                return True
            error = ""
            if method == "POST" and urlparse(self.path).path == "/login":
                length = min(int(self.headers.get("Content-Length") or 0), 4096)
                password = parse_qs(self.rfile.read(length).decode("utf-8")).get("password", [""])[0]
                key, error = app.gate.login(network.load(app.config_dir), self.client_address[0], password)
                if key:
                    self.send_response(303)
                    self.send_header("Location", "/")
                    self.send_header("Set-Cookie", f"{network.COOKIE}={key}; Path=/; HttpOnly; SameSite=Strict; "
                                                   f"Max-Age={network.SESSION_DAYS * 86400}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return False
            if urlparse(self.path).path.startswith("/api/"):
                self._send(401, json.dumps({"error": "Войдите заново — обновите страницу."}, ensure_ascii=False))
            else:
                page = network.LOGIN_PAGE.replace("{{ERROR}}", f'<p class="err">{error}</p>' if error else "")
                self._send(401 if error else 200, page, "text/html; charset=utf-8")
            return False

        def _serve(self, method):
            if remote:
                if not self._login(method):
                    return
            elif not self._local_host():
                return self._send(403, '{"error": "forbidden"}')
            url = urlparse(self.path)
            if method == "GET" and url.path in ("/", "/index.html"):
                return self._send(200, app.page(remote), "text/html; charset=utf-8")
            if method == "GET" and url.path == "/help":
                self.send_response(301)
                self.send_header("Location", "/help/")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if method == "GET" and url.path.startswith("/help/"):          # «Помощь»: README и docs/
                found = help.page(url.path)
                return self._send(200, found[1], found[0]) if found else self._send(404, '{"error": "not found"}')
            if method == "GET" and STATIC.fullmatch(url.path):             # стили и скрипты окна
                f = WEB / url.path.lstrip("/")
                if f.is_file():
                    return self._send(200, f.read_bytes(), STATIC_TYPES[f.suffix])
            if not url.path.startswith("/api/"):
                return self._send(404, '{"error": "not found"}')
            if not secrets.compare_digest(self.headers.get("X-Token", ""), app.token):
                return self._send(403, json.dumps({"error": "Неверный ключ — перезапустите окно программы."},
                                                  ensure_ascii=False))
            data = {}
            if method == "POST":
                length = int(self.headers.get("Content-Length") or 0)
                data = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            try:
                result = app.handle(method, url.path, parse_qs(url.query), data, remote)
                self._send(200, json.dumps(result, ensure_ascii=False))
            except Forbidden as e:
                self._send(403, json.dumps({"error": str(e)}, ensure_ascii=False))
            except (AssistantError, KeyError, ValueError) as e:
                self._send(400, json.dumps({"error": str(e)}, ensure_ascii=False))

        def do_GET(self):
            self._serve("GET")

        def do_POST(self):
            self._serve("POST")

    return Handler


class Server(ThreadingHTTPServer):
    # Окно при загрузке разом просит ~15 файлов (скрипты, стили), а очередь соединений по умолчанию — 5:
    # лишние браузер получал сброшенными, и часть скриптов не загружалась
    request_queue_size = 64


def make_server(app, port=PORT):
    try:
        return Server(("127.0.0.1", port), handler_for(app))
    except OSError:                                  # порт занят — например, окно уже открыто
        return Server(("127.0.0.1", 0), handler_for(app))


def backup_on_start(profiles_root):
    """Автокопия профилей раз в неделю. Не вышло (нет места, нет прав) — программа работает дальше."""
    try:
        backup.auto(profiles_root, log=lambda m: print(m, flush=True))
    except Exception as e:                           # noqa: BLE001
        print(f"Резервная копия не сделана: {e}", flush=True)


def serve(open_browser=True, port=PORT):
    app = App()
    server = make_server(app, port)
    app.server = server                               # для «Выйти из программы»
    app.start_lan()
    threading.Thread(target=backup_on_start, args=(app.config_dir,), daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    how_to_quit = ("«Параметры → Выйти из программы» в окне" if getattr(sys, "frozen", False)
                   else "Ctrl+C в этом окне или «Параметры → Выйти из программы»")
    print(f"Окно программы: {url}\nДанные не покидают этот компьютер. Закрыть программу — {how_to_quit}.", flush=True)
    if app.lan:
        print("Доступ из домашней сети (с паролем): " + ", ".join(app.network_state()["urls"]), flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.stop_lan()
        server.server_close()
