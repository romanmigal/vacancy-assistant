"""Задачи для кнопок окна: что делает каждое действие и нужна ли ему модель.

Каждое действие — функция (profile, data, env) → (заголовок задачи, work(log)). Проверки, которые можно сделать
сразу, — в самой функции: ошибка видна до постановки в очередь. Тяжёлая работа — в work, её выполняет очередь.
env — подмена hh.ru и модели в тестах (fetch_page, ask); hh_kw — fetch_page для функций hh.ru и лент.
"""
from collections import namedtuple

from . import actual, analysis, calibration, cloud, company, contacts, fix, gaps, hh, letter_templates, market, rss, setup, sites, tune
from .errors import AssistantError
from .files import REFERRER_ID_PROP, REFERRER_PROP, read_meta, read_prop, read_vacancy, say_decision
from .hh import phase
from .model import current_model
from .textio import write_json
from .vacancies import analyzed_with_status, changed_with_status, vacancy_file, vacancy_rows, with_status

LOCAL_OFF = ("Локальная модель не запущена: запустите Ollama (приложение Ollama или команда  ollama serve  в терминале) "
             "и повторите.")
NO_MODEL_ERROR = "Нужна модель — включите локальную или облачную в «Параметры → Настройки»."

Env = namedtuple("Env", "fetch_page ask hh_kw")
Action = namedtuple("Action", "make model single")
WORK = {}


def action(name, model=False, single=False):
    """Регистрирует действие. model — нужна модель: в режиме «Без модели» кнопки неактивны, а сервер отказывает
    (на случай, если кнопку обошли); поиск и добавление вакансий работают и без модели — вакансии сохраняются
    без разбора. single — одиночная задача для одной вакансии, по кнопке: пачка пропускает её вперёд."""
    def register(make):
        WORK[name] = Action(make, model, single)
        return make
    return register


def local_off(profile, ask=None):
    """Профиль оценивает локальной моделью, а Ollama не запущена. ask — подмена модели в тестах: тогда не проверяем."""
    return ask is None and not profile.no_model and not cloud.active(profile) and setup.ollama_models() is None


def analyze_and_write(profile, log, ask, only=None):
    """Разбор новых вакансий (only — только этих). Письма сами не пишутся — только кнопкой во вкладке «Письма» карточки.
    Локальная модель не запущена — вакансии остаются неразобранными, поиск не падает: разобрать их можно потом
    кнопкой ↻ «Пересчитать оценки» → «Неразобранные»."""
    if local_off(profile, ask):
        files = [profile.vacancies / n for n in only] if only is not None else sorted(profile.vacancies.glob("*.md"))
        left = sum(1 for f in files if analysis.unanalyzed(profile.results / f.name))
        if left:
            log(f"Локальная модель не запущена — вакансии сохранены без оценки, ждут разбора: {left}. Запустите Ollama "
                "(приложение Ollama или команда  ollama serve  в терминале) и нажмите ↻ «Пересчитать оценки» → «Неразобранные».")
        return
    analysis.analyze(profile, log=log, ask=ask, summary=False, only=only)


def make_work(profile, action_name, data, fetch_page=None, ask=None):
    """Задача для кнопки окна: (заголовок, work). fetch_page и ask — подмена hh.ru и модели в тестах."""
    act = WORK.get(action_name)
    if not act:
        raise AssistantError(f"Неизвестное действие «{action_name}»")
    if act.model and profile.no_model:
        raise AssistantError(NO_MODEL_ERROR)
    if act.model and local_off(profile, ask):        # сразу, а не ошибкой на первой же вакансии
        raise AssistantError(LOCAL_OFF)
    return act.make(profile, data, Env(fetch_page, ask, {"fetch_page": fetch_page} if fetch_page else {}))


# ── Поиск и добавление вакансий ────────────────────────────────────────────

@action("update")
def _update(profile, data, env):
    feeds = rss.enabled(profile)
    if not feeds:
        hh.require_auto(profile)            # поиск на hh.ru выключен и лент нет — отказ сразу, без обращения к сети
    limit = int(data.get("limit") or 0) or None

    def work(log):
        got = []
        if not profile.hh_auto:
            log("Поиск на hh.ru выключен — читаю только ленты вакансий.")
        elif profile.searches.exists() and hh.read_queries(profile):
            got = hh.search(profile, log, limit=limit, **env.hh_kw) or []
        else:
            log("Поисковых запросов нет (поиски.txt) — только разбор.")
        left = rss.leftover(limit or profile.search_limit, len(got))   # лимит общий: ленты — остаток после hh.ru
        if feeds and left == 0:
            log("Лимит вакансий за поиск набран на hh.ru — ленты Хабр Карьеры и GeekJob прочитаю при следующем поиске.")
        elif feeds:                         # RSS Хабр Карьеры и GeekJob
            rss.search(profile, log, ask=env.ask, limit=left, **env.hh_kw)
        analyze_and_write(profile, log, env.ask)
    return "Найти новые вакансии", work


@action("add", single=True)
def _add(profile, data, env):               # ссылки hh.ru и любых других сайтов
    links = data.get("links", "")
    hh_ids, other = sites.split_links(links)
    if not hh_ids and not other:
        raise AssistantError("Не нашёл ссылок на вакансии.")
    if not other:
        hh.require_auto(profile)            # только ссылки hh.ru, а поиск на hh выключен — отказ без сети

    def work(log):                          # разбираются только добавленные: остальное — дело пачки
        added = sites.add_any(profile, links, log, env.fetch_page, env.ask)
        if added:
            analyze_and_write(profile, log, env.ask, only=[f.name for f in added])
    return "Добавить вакансию по ссылке", work


@action("add_text", single=True)
def _add_text(profile, data, env):          # вакансия, вставленная текстом (сайт не отдаёт страницу)
    if len((data.get("text") or "").strip()) < 100:
        raise AssistantError("Вставьте текст вакансии целиком — название, обязанности, требования.")

    def work(log):
        added = sites.add_text(profile, data.get("text", ""), data.get("link", ""), log, env.ask)
        if added:                                   # None — та же вакансия уже есть
            analyze_and_write(profile, log, env.ask, only=[added.name])
    return "Добавить вакансию из текста", work


@action("add_page", single=True)
def _add_page(profile, data, env):          # страница вакансии, сохранённая в браузере, — без сети
    page, name = data.get("page") or "", data.get("name") or ""
    if len(page) < 500 or "<" not in page:
        raise AssistantError("Это не страница вакансии: загрузите файл .html, сохранённый в браузере (⌘S или Ctrl+S).")

    def work(log):
        added = sites.add_saved(profile, page, name, log, env.ask)
        if added:
            analyze_and_write(profile, log, env.ask, only=[added.name])
    return "Добавить вакансию из сохранённой страницы", work


# ── Разбор и переоценка ────────────────────────────────────────────────────

@action("analyze", model=True)
def _analyze(profile, data, env):
    return "Разбор новых вакансий", lambda log: analyze_and_write(profile, log, env.ask)


@action("refresh", model=True)
def _refresh(profile, data, env):           # после правки профиля: переоценка и новые версии писем по статусам
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
            analysis.analyze(profile, log=log, ask=env.ask, summary=False, only=targets())
        if reletters:
            analysis.write_letters(profile, log=log, ask=env.ask, summary=False, only=with_status(profile, reletters))
    return ("Переоценка вакансий" if reanalyze else "Новые версии писем"), work


@action("rescore_all", model=True)
def _rescore_all(profile, data, env):       # кнопка ↻ в шапке: устаревшие или все разобранные в выбранных разделах
    statuses = set(data.get("statuses") or [])
    if data.get("mode") == "new":           # не разобраны: модель была выключена, Ollama не запущена
        names = [n for n in with_status(profile, statuses) if analysis.unanalyzed(profile.results / n)]
        if not names:
            raise AssistantError("В выбранных разделах нет неразобранных вакансий.")
        return "Разбор неразобранных вакансий", lambda log: analysis.analyze(profile, log=log, ask=env.ask, summary=False, only=names)
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
                _, result, sec = analysis.full_analysis(profile, path, log=log, ask=env.ask)
                log(f"      оценка {result['score']}/10, откликаться: {say_decision(result['decision'])} ({sec} с)")
            except AssistantError as e:
                if type(e).__name__ == "Stopped":            # «Остановить» — не ошибка разбора
                    raise
                log(f"      {e}")
    return "Пересчёт оценок по новым данным", work


@action("refresh_card", single=True)
def _refresh_card(profile, data, env):      # кнопка в карточке: текст вакансии и полный разбор заново
    path = vacancy_file(profile, data.get("n", 0))

    def work(log):
        phase(log, "Разбираю вакансию заново по текущим настройкам")
        link, seen = read_vacancy(path)[1]["link"], {}
        if "hh.ru/" in link:                                          # hh.ru: только актуальность, текст прежний
            seen["actual"] = actual.check_hh(profile, link, env.fetch_page or hh.fetch, log,
                                             on_page=lambda page, get: (company.from_page(profile, path, page, get, log),
                                                                        hh.set_posted(path, hh.posted(page))))
        else:                                                         # другой сайт: перечитать страницу
            sites.refresh(profile, path, log, env.fetch_page or sites.fetch, env.ask, seen)
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
        target, result, sec = analysis.full_analysis(profile, path, log=log, ask=env.ask)
        log(f"      оценка {result['score']}/10, откликаться: {say_decision(result['decision'])} ({sec} с)")
        if not actual.read(target)["checked"]:
            actual.record(target, state)                              # разбора не было — пишем в новый
    return "Разобрать заново", work


# ── Критерии: калибровка и правки ──────────────────────────────────────────

@action("tune", model=True)
def _tune(profile, data, env):              # калибровка: автонастройка критериев по своим оценкам
    rounds = max(1, min(5, int(data.get("rounds") or 3)))
    only = calibration.picked(profile)

    def work(log):
        phase(log, "Автонастройка критериев")
        tune.tune(profile, rounds, log=log, ask=env.ask, only=only)
        # Состав последней калибровки: значит, калибровку уже делали — больше не предлагать
        write_json(profile.dir / calibration.FILE, {**calibration.read(profile), "last": sorted(only)})
    return "Автонастройка критериев", work


@action("fix_suggest", model=True, single=True)
def _fix_suggest(profile, data, env):       # окно «Мои оценки»: правка критериев и проверка на вакансии
    n = int(data["n"])
    if data.get("direction") not in ("up", "down"):
        raise AssistantError("Укажите, выше или ниже должна быть оценка.")

    def work(log):
        phase(log, "Правка критериев по вакансии")
        fix.suggest(profile, n, data, log, ask=env.ask)
    return "Правка критериев по вакансии", work


@action("fix_check", model=True)
def _fix_check(profile, data, env):         # та же правка — на уже оценённых вакансиях: не сломали ли остальное
    n = int(data["n"])

    def work(log):
        phase(log, "Проверка правки на оценённых вакансиях")
        fix.check_reference(profile, n, log, ask=env.ask)
    return "Проверка правки критериев", work


@action("fix_recheck", model=True, single=True)
def _fix_recheck(profile, data, env):       # свои правки критериев, резюме, «о себе» — и пересчёт этой вакансии
    n = int(data["n"])

    def work(log):
        phase(log, "Пересчёт вакансии после правки")
        fix.recheck(profile, n, data, log, ask=env.ask)
    return "Пересчёт вакансии после правки", work


# ── «Резюме против рынка» ──────────────────────────────────────────────────

@action("market_recheck", model=True)
def _market_recheck(profile, data, env):    # правка резюме и «о себе» — и пересчёт вакансий
    ns = [int(n) for n in data.get("ns") or []]
    if not ns:
        raise AssistantError("Отметьте вакансии, которые пересчитать.")

    def work(log):
        phase(log, f"Пересчёт {len(ns)} {'вакансии' if len(ns) == 1 else 'вакансий'} после правки")
        gaps.recheck(profile, ns, data, log, ask=env.ask)
    return "Резюме против рынка: пересчёт", work


@action("market_advice", model=True, single=True)
def _market_advice(profile, data, env):     # что дописать и что нарастить
    def work(log):
        phase(log, f"Резюме против рынка: что прокачать — моделью {current_model()}")
        market.write_advice(profile, vacancy_rows(profile), log, env.ask or analysis.ask_model, data.get("since"))
    return "Резюме против рынка: формулировки", work


# ── Тексты по вакансии: письма, интервью, резюме ───────────────────────────

def _analyzed(profile, data, missing):
    """Файл разбора вакансии из запроса; вакансия не разобрана — ошибка с текстом missing."""
    return vacancy_file(profile, data.get("n", 0), profile.results, missing)


def _full_first(profile, result, log, env, purpose):
    """Тексту нужен полный разбор (сильные стороны, пробелы, требования): есть только быстрая оценка
    или разбора без модели — сначала полный."""
    if (read_meta(result) or {}).get("stage") in ("short", analysis.NO_MODEL):
        phase(log, f"Полный разбор моделью {current_model()} — нужен для {purpose}")
        analysis.full_analysis(profile, profile.vacancies / result.name, log=log, ask=env.ask)


@action("letter", model=True, single=True)
def _letter(profile, data, env):            # кнопка в карточке: письмо для одной вакансии при любой оценке
    result = _analyzed(profile, data, "Письмо можно написать после разбора вакансии.")
    tpl = letter_templates.get(profile, int(data["template"]) if data.get("template") else None)
    example = (data.get("example") or "").strip() or None     # шаблон, поправленный для этого письма
    if example and data.get("save_example") and example != tpl["text"]:     # …и сохранённый в шаблон
        letter_templates.save(profile, tpl["id"], tpl["name"], example, source="правка перед письмом")

    def work(log):
        _full_first(profile, result, log, env, "письма")
        phase(log, f"Пишу {'новую версию письма' if (profile.letters / result.name).exists() else 'сопроводительное письмо'} "
                   f"моделью {current_model()}")
        log(f"Пишу письмо: {read_meta(result)['title']}")
        analysis.write_letter(profile, result, log=log, ask=env.ask, example=example, template=tpl["id"])
    return "Сопроводительное письмо", work


@action("referrer_letter", model=True, single=True)
def _referrer_letter(profile, data, env):   # вкладка «Письма»: сообщение референсеру вакансии
    result = _analyzed(profile, data, "Написать референсеру можно после разбора вакансии.")
    to = read_prop(result, REFERRER_PROP)
    if not to:
        raise AssistantError("Сначала укажите референсера — в поле «Референсер» карточки: из контактов или вручную.")
    person = next((c for c in contacts.load(profile) if c["id"] == read_prop(result, REFERRER_ID_PROP)), {})
    about = "; ".join(x for x in (person.get("note"), f"статус переписки: {dict(contacts.STATUSES)[person['status']]}"
                                  if person.get("status") else "") if x)

    def work(log):
        _full_first(profile, result, log, env, "сообщения")
        phase(log, f"Пишу сообщение референсеру моделью {current_model()}")
        log(f"Кому: {to}")
        analysis.write_referrer_letter(profile, result, to, about, data.get("channel", "telegram"), data.get("goal", "pass"),
                                       data.get("extra", ""), log=log, ask=env.ask)
    return "Сообщение референсеру", work


@action("interview", model=True, single=True)
def _interview(profile, data, env):         # кнопка в карточке: истории STAR к собеседованию
    result = _analyzed(profile, data, "Подготовиться к интервью можно после разбора вакансии.")

    def work(log):
        _full_first(profile, result, log, env, "подготовки")
        phase(log, f"Готовлю истории к интервью моделью {current_model()}")
        log(f"Подбираю истории из резюме под требования: {read_meta(result)['title']} (1–3 минуты)")
        analysis.write_interview(profile, result, log=log, ask=env.ask)
    return "Подготовка к интервью", work


@action("interview_questions", model=True, single=True)
def _interview_questions(profile, data, env):   # кнопка в карточке: вопросы работодателю к готовой подготовке
    result = _analyzed(profile, data, "Вопросы работодателю можно подготовить после разбора вакансии.")

    def work(log):
        _full_first(profile, result, log, env, "вопросов")
        phase(log, f"Готовлю вопросы работодателю моделью {current_model()}")
        log(f"Вопросы по пробелам и неясностям разбора: {read_meta(result)['title']} (до минуты)")
        analysis.write_questions(profile, result, log=log, ask=env.ask)
    return "Вопросы работодателю", work


@action("resume_fit", model=True, single=True)
def _resume_fit(profile, data, env):        # кнопка в карточке: резюме под вакансию
    result = _analyzed(profile, data, "Подогнать резюме можно после разбора вакансии.")

    def work(log):
        _full_first(profile, result, log, env, "резюме")
        phase(log, f"Подгоняю резюме под вакансию моделью {current_model()}")
        log(f"Что поднять, «Обо мне» и навыки: {read_meta(result)['title']} (1–2 минуты)")
        analysis.write_resume_fit(profile, result, log=log, ask=env.ask)
    return "Резюме под вакансию", work


NEEDS_MODEL = frozenset(a for a, x in WORK.items() if x.model)
SINGLE = frozenset(a for a, x in WORK.items() if x.single)
