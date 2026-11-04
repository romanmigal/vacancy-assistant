"""Резюме против рынка (#70, #80): чего не хватает в резюме и что прокачать. Два источника:
- вакансии, на которые вы откликались (проставлен этап): оценка и решение модели бывают неточными, а отклик — ваш выбор;
- расхождения со своей оценкой с выбранной даты (gaps.py): вы сами считаете вакансию подходящей, а модель
  по резюме отвергла — самый честный сигнал, что в резюме не видно нужного работодателю.

Без модели:
- ключевые слова из текстов этих вакансий (технологии, методологии, стандарты — латиницей и аббревиатуры):
  в скольких вакансиях встречается и есть ли в резюме и «Дополнительно о себе»; синонимы и написание
  выравниваются («ITIL» / «итил», «P&L» / «PnL», «1С» / «1C»);
- требования, которые модель в разборах этих вакансий чаще всего отмечала ❌, — похожие склеены в одно;
- проверка на роботов-фильтры (ATS): разделы, даты работы, длина.
С моделью — что дописать («было → стало», только из фактов резюме) и что нарастить. Резюме и «о себе» правятся
в окне — с пересчётом отмеченных вакансий (gaps.recheck). Результат с датой — в рынок.json: после обновления
резюме видно, сколько пробелов было и сколько стало.
"""
import re
import time
from datetime import date

from . import answer, gaps, settings, setup
from .files import analysis_body, numbered_files, read_vacancy
from .textio import read_json, read_text, write_json

FILE = gaps.FILE             # «рынок.json»: {"history": [{date, missing, gaps, vacancies}], "advice": {…}, "recheck": {…}}
MIN_SHARE = 0.15             # слово показываем, если оно есть хотя бы в такой доле вакансий (и не меньше чем в двух)
TOP_GAPS = 8                 # сколько пробелов отдаём модели
TOP_VACANCIES = 15           # и сколько вакансий «модель — нет, вы — да»

LATIN = re.compile(r"(?<![\w@.])[A-Za-z][A-Za-z0-9+#&]*(?:[.-][A-Za-z0-9+#&]+)*")
KEEP_SLASH = {"ci/cd"}                 # «CI/CD» — одно слово; «ITSM/ITIL», «Go/Python» — разные
CYR_ABBR = re.compile(r"(?<![\w])(?:[А-ЯЁ]{2,6}|1С)(?![\w])")
# Общие слова и названия, а не навыки
STOP = set("""a an and or the of for to in on at by with from as is are be we you our your it its this that will can
may must should have has not no yes etc e g i ie vs per via up out new all any more most other such into over
team teams work working experience years year level strong good knowledge skills skill ability plus nice
engineering engineer engineers code coding based driven first hands on hands-on ceo coo cfo cmo hr
senior middle junior lead head chief officer director manager management manage
hh ru com www http https pdf doc docx job jobs career careers company group ltd llc inc""".split())
CYR_STOP = {"ООО", "ОАО", "ПАО", "ЗАО", "АО", "НАО", "ИП", "РФ", "ДМС", "ТК", "НДФЛ", "ЗП", "ГК", "МСК", "СПБ", "ЕАО",
            "НЕ", "НА", "ИЛИ", "ДЛЯ", "ОТ", "ДО", "ВСЕ", "ЭТО", "КАК", "МЫ", "ВЫ", "НАШ", "ГОД", "ЛЕТ", "ТД", "ТП", "СМ"}
ALIASES = {"итил": "itil", "pnl": "p&l", "п&л": "p&l", "1с": "1c", "эрп": "erp", "срм": "crm", "скрам": "scrum",
           "аджайл": "agile", "девопс": "devops", "кубернетес": "kubernetes", "k8s": "kubernetes", "postgres": "postgresql",
           "js": "javascript", "ms project": "msproject", "power bi": "powerbi", "ии": "ai", "ml": "machine learning",
           "иб": "информационная безопасность", "is": "информационная безопасность", "цод": "цод", "dc": "цод"}
WORD = re.compile(r"[a-zа-яё0-9+#&]+")
# Слова, которые есть почти в любом требовании, — по первым 5 буквам; группы по ним не склеиваем
COMMON = {w[:5] for w in """опыт работы работа знание знания умение навыки понимание лет года год более менее наличие
успешный подтверждённый резюме требования области уровня компании компаниях проектов проекты глубокое также которые
крупных крупной ролях роли управления управление""".replace("ё", "е").split()}


def norm(term):
    """Ключ слова для сравнения: строчными, ё → е, без точек и дефисов, синонимы — к одному написанию."""
    t = term.lower().replace("ё", "е").strip(" .,-/")
    t = re.sub(r"[.\-/]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return ALIASES.get(t, ALIASES.get(t.replace(" ", ""), t)).replace(" ", "")


def _body(text):
    """Описание вакансии без шапки и без ссылок и почты."""
    body = text.split("\n---\n", 1)[-1]
    return re.sub(r"https?://\S+|[\w.+-]+@[\w-]+(?:\.[\w-]+)+", " ", body)


def terms(text):
    """Ключевые слова текста: {ключ: как написано}. Слова латиницей подряд, через пробел, — одно
    («Power BI», «disaster recovery», «open source»), до трёх; общие слова (and, experience, team) разрывают
    и не считаются. Аббревиатуры кириллицей (ИБ, ЦОД, МСФО)."""
    out = {}
    text = re.sub(r"\b(CI)/(CD)\b", r"\1\2", text, flags=re.I)
    words = [(m.group(0), m.start(), m.end()) for m in LATIN.finditer(text)]
    run = []

    def flush():
        if run:
            phrase = text[run[0][1]:run[-1][2]]
            if len(phrase) >= 2 and not (phrase.islower() and len(phrase) < 3):
                out.setdefault(norm(phrase), "CI/CD" if phrase.lower() == "cicd" else phrase)
            run.clear()
    for k, (w, s, e) in enumerate(words):
        stop = w.lower() in STOP
        joined = run and len(run) < 3 and re.fullmatch(r"[ \t]+", text[run[-1][2]:s])
        if stop or not joined:
            flush()
        if not stop:
            run.append((w, s, e))
    flush()
    for m in CYR_ABBR.finditer(text):
        if m.group(0) not in CYR_STOP:
            out.setdefault(norm(m.group(0)), m.group(0))
    return out


def has(key, text_keys, squashed):
    """Есть ли слово в резюме: среди его ключевых слов или (для длинных) в тексте без пробелов."""
    return key in text_keys or (len(key) >= 5 and key in squashed)


def _squash(text):
    return "".join(WORD.findall(norm_text(text)))


def norm_text(text):
    t = text.lower().replace("ё", "е")
    for a, b in ALIASES.items():
        t = re.sub(rf"(?<![\w]){re.escape(a)}(?![\w])", b, t)
    return t


def _stems(text):
    """Значимые слова требования — по первым 5 буквам: «облачных» и «облако» близко, а «опыт», «работы» — нет."""
    t = text.lower().replace("ё", "е")
    return ({w[:5] for w in re.findall(r"[а-яё0-9]{3,}", t) if w[:5] not in COMMON}
            | {w[:5] for w in re.findall(r"[a-z]{2,}", t) if w not in STOP})


def cluster(items, threshold=0.5):
    """Похожие требования — в одну группу: [{text, count, vacancies: [n]}], частые — первыми. Похожи — если
    у короткого из двух не меньше половины значимых слов общие («Опыт внедрения AI/ML» ~ «AI-native подходы»)."""
    groups = []
    close = lambda a, b: len(a & b) / min(len(a), len(b))
    for text, n in items:
        st = _stems(text)
        if not st:
            continue
        best = max(groups, key=lambda g: close(st, g["first"]), default=None)
        if best and close(st, best["first"]) >= threshold:
            best["texts"].append(text)
            if n not in best["vacancies"]:
                best["vacancies"].append(n)
        else:
            groups.append({"texts": [text], "first": st, "vacancies": [n]})
    out = [{"text": min(g["texts"], key=len), "variants": len(g["texts"]), "count": len(g["vacancies"]),
            "vacancies": g["vacancies"]} for g in groups]
    return sorted(out, key=lambda g: (-g["count"], g["text"]))


def _requirement(text):
    """«Опыт X от 5 лет — ❌ (пояснение)» → «Опыт X от 5 лет»."""
    return re.split(r"\s+[—–-]\s+(?:✅|❌|❓)", text)[0].strip(" .")


def ats(resume):
    """Проверка на роботов-фильтры: [{ok, text}]. Роботы (ATS) ищут стандартные разделы и даты работы."""
    heads = [h.lower() for h in re.findall(r"^#{2,3}\s+(.+)$", resume, re.M)] + \
            [h.lower() for h in re.findall(r"^\*\*([^*]{3,40})\*\*\s*$", resume, re.M)]
    has_head = lambda *words: any(any(w in h for w in words) for h in heads)
    jobs = re.findall(r"^###[^\n]*\d{4}|^\*\*[^*\n]+\*\*\s*·[^\n]*\d{4}", resume, re.M)
    years = re.findall(r"(?:19|20)\d{2}", resume)
    n = len(resume)
    return [
        {"ok": has_head("опыт", "experience"), "text": "Раздел «Опыт работы»" + ("" if has_head("опыт", "experience") else " — не найден: роботы ищут его по заголовку")},
        {"ok": has_head("образован", "education"), "text": "Раздел «Образование»" + ("" if has_head("образован", "education") else " — не найден")},
        {"ok": has_head("навык", "skills", "компетенц"), "text": "Раздел «Навыки» или «Ключевые навыки»" + ("" if has_head("навык", "skills", "компетенц")
                                                                                                         else " — не найден: в нём роботы ищут ключевые слова вакансии")},
        {"ok": bool(jobs) or len(years) >= 2, "text": f"Даты работы — {'у мест работы есть годы' if jobs or len(years) >= 2 else 'не найдены: укажите годы начала и конца'}"},
        {"ok": 1500 <= n <= 15000, "text": f"Длина — {n} знаков" + (": слишком коротко, роботу не за что зацепиться" if n < 1500 else
                                                                    ": длинно — рекрутер и робот читают первые 2 страницы" if n > 15000 else "")},
        {"ok": not re.search(r"\|.+\|.+\|", resume), "text": "Без таблиц" + ("" if not re.search(r"\|.+\|.+\|", resume)
                                                                           else " — в резюме есть таблица: роботы часто читают её с ошибками")},
    ]


def pick(rows):
    """Вакансии, на которые стоит равняться: с проставленным этапом отклика (любым, и «Отказ» тоже).
    Требования с ❌ — только у разобранных из них, слова — у всех."""
    return [r for r in rows if (r.get("funnel") or {}).get("stage")]


def report(profile, rows, since=None):
    """Всё для окна «Резюме против рынка» — без модели. since — с какой даты своей оценки искать расхождения."""
    good = pick(rows)
    own = gaps.discrepancies(profile, rows, since)
    files = numbered_files(profile.vacancies)
    resume = profile.with_facts(profile.read_resume()) if profile.resume.exists() else ""
    rkeys, rsq = set(terms(resume)) | set(WORD.findall(norm_text(resume))), _squash(resume)
    found, failed = {}, []
    for r in good:
        path = files.get(r["n"])
        if not path:
            continue
        for key, shown in terms(_body(read_vacancy(path)[0])).items():
            f = found.setdefault(key, {"term": shown, "vacancies": []})
            f["vacancies"].append(r["n"])
        result = profile.results / path.name
        if result.exists():
            for q in answer.parse(analysis_body(read_text(result)))["requirements"]:
                if not q["ok"]:
                    failed.append((_requirement(q["text"]), r["n"]))
    seen = {r["n"] for r in good}                     # расхождения без отклика — их ❌ тоже в общий список
    failed += [(q, v["n"]) for v in own["under"] if v["n"] not in seen for q in v["failed"]]
    need = max(2, round(len(good) * MIN_SHARE))
    words = [{"term": f["term"], "count": len(f["vacancies"]), "vacancies": f["vacancies"], "in_resume": has(k, rkeys, rsq)}
             for k, f in found.items() if len(f["vacancies"]) >= need]
    words.sort(key=lambda w: (w["in_resume"], -w["count"], w["term"].lower()))
    groups = cluster(failed)
    gaps_, rare = [g for g in groups if g["count"] >= 2], [g for g in groups if g["count"] < 2]
    data = read_json(profile.dir / FILE, {})
    profiled = setup.answers_from_profile(profile)
    return {"vacancies": len(good), "total": len(rows), "need": need,
            "words": words, "missing": sum(1 for w in words if not w["in_resume"]), "gaps": gaps_[:15], "rare": rare[:30],
            "ats": ats(profile.read_resume() if profile.resume.exists() else ""),
            "history": data.get("history", [])[-6:], "advice": data.get("advice"), "own": own, "recheck": data.get("recheck"),
            "resume": profiled["resume"], "facts": profiled["facts"], "resume_editable": profiled["resume_editable"],
            "resume_hash": profile.resume_hash() if profile.resume.exists() else ""}


def remember(profile, rep, today=None):
    """Запомнить итог проверки (одна запись на день): сколько пробелов — чтобы видеть прогресс."""
    data = read_json(profile.dir / FILE, {})
    day = (today or date.today()).isoformat()
    hist = [h for h in data.get("history", []) if h["date"] != day]
    hist.append({"date": day, "missing": rep["missing"], "gaps": len(rep["gaps"]), "vacancies": rep["vacancies"],
                 "resume": profile.resume_hash() if profile.resume.exists() else ""})
    data["history"] = hist[-30:]
    write_json(profile.dir / FILE, data)


def advice_prompt(profile, rep):
    """Что дописать и что нарастить: расхождения со своей оценкой и главные пробелы откликов — только из фактов резюме."""
    under = rep["own"]["under"][:TOP_VACANCIES]
    vacancies = "\n\n".join(
        f"{v['title']} — {v['company']}\nМоя причина: {v['mine']['reason'] or 'не указана'}\nНе нашла в резюме:\n"
        + ("\n".join(f"- {q}" for q in v["failed"]) or "- (требований с ❌ нет — см. нарушенные критерии)")
        + "".join(f"\nНарушен К{c['k']}: {c['text']}" for c in v["criteria"])
        for v in under) or "— (таких вакансий нет)"
    lines = [f"- {g['text']} (в {g['count']} вакансиях)" for g in (rep["gaps"] + rep["rare"])[:TOP_GAPS]]
    lines += [f"- {w['term']} (в {w['count']} вакансиях)" for w in rep["words"] if not w["in_resume"]][:max(0, TOP_GAPS + 2 - len(lines))]
    t = read_text(settings.MARKET_TEMPLATE)
    return (t.replace("{who}", profile.config["письмо"]["кому_помогаем"]).replace("{count}", str(rep["vacancies"]))
            .replace("{vacancies}", vacancies).replace("{gaps}", "\n".join(lines) or "—")
            .replace("{resume}", profile.with_facts(profile.read_resume())))


def write_advice(profile, rows, log, ask, since=None):
    """Что дописать и что нарастить — моделью: результат — в рынок.json с датой."""
    from .model import current_model
    rep = report(profile, rows, since)
    if not rep["gaps"] and not rep["rare"] and not rep["missing"] and not rep["own"]["under"]:
        log("Пробелов не нашлось — подсказывать нечего.")
        return None
    start = time.time()
    text = ask(advice_prompt(profile, rep), settings.MODEL, settings.MARKET_OPTIONS).strip()
    data = read_json(profile.dir / FILE, {})
    data["advice"] = {"date": date.today().isoformat(), "text": text, "model": current_model(),
                      "vacancies": rep["vacancies"], "since": rep["own"]["since"], "under": len(rep["own"]["under"]),
                      "resume": profile.resume_hash()}
    write_json(profile.dir / FILE, data)
    log(f"      готово ({round(time.time() - start)} с)")
    return text
