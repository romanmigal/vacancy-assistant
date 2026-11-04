"""Калибровка критериев (#81): набор вакансий из своих недавних оценок, расхождения с моделью — первыми.

Набор программа подбирает сама: вакансии со своей оценкой и разбором модели, свежие по дате своей оценки.
Сначала — по 2 на каждое своё решение (да / возможно / нет), затем те, где оценка модели расходится с вашей,
затем совпадающие — чтобы правка не сломала то, что уже работает. Размер набора — по модели профиля: один
круг автонастройки (прогон текущих критериев и кандидата) — не дольше ~5 минут. Вакансии можно убрать из
набора и добавить другие оценённые — правки набора в калибровка.json: {"excluded", "added", "last"}.
"""
from . import analysis, cloud, ratings, summary, tune
from .files import decision_yes, numbered_files, read_meta, read_note, read_vacancy
from .textio import read_json, write_json

FILE = "калибровка.json"
NEED = 10                 # столько разобранных вакансий — пора предложить калибровку
MINIMUM = 6               # меньше своих оценок в наборе — автонастройку не запустить (tune.tune)
PER_DECISION = 2          # на каждое своё решение — хотя бы столько, если такие есть
# Размер набора по модели: облачная отвечает за секунды, локальная быстрой оценкой — ~15 с, полным разбором — ~1 мин
LIMITS = {"cloud": 12, "two_stage": 8, "full": 6}
DIVERGE = 2               # оценки различаются на столько и больше — расходится


def read(profile):
    return read_json(profile.dir / FILE, {})


def limit(profile):
    return LIMITS["cloud" if cloud.active(profile) else "two_stage" if profile.two_stage else "full"]


def diverges(v):
    """Ваше решение не совпало с решением модели или оценки различаются на DIVERGE и больше."""
    if v["yes"] != v["model_yes"]:
        return True
    return v["score"] is not None and v["model_score"] is not None and abs(v["score"] - v["model_score"]) >= DIVERGE


def suggest(rated, size):
    """Набор по умолчанию из оценённых (rated — свежие первыми): по PER_DECISION на каждое решение,
    затем расходящиеся, затем совпадающие — не больше size. Номера в порядке показа."""
    order = sorted(rated, key=lambda v: not v["diverge"])         # сортировка устойчивая: внутри — свежие первыми
    picked = []
    for word in ratings.DECISIONS:
        picked += [v["n"] for v in order if v["decision"] == word][:PER_DECISION]
    picked = set(picked[:size])
    for v in order:
        if len(picked) >= size:
            break
        picked.add(v["n"])
    return [v["n"] for v in order if v["n"] in picked]


def vacancies(profile):
    """Разобранные моделью вакансии: свои оценки (rated — свежие первыми) и ещё не оценённые (unrated)."""
    mine = ratings.read_rows(profile)
    flags = summary.read_flags(profile)
    rated, unrated = [], []
    for n, path in sorted(numbered_files(profile.vacancies).items(), reverse=True):
        result = profile.results / path.name
        meta = read_meta(result) if result.exists() else None
        if not meta or meta.get("stage") == analysis.NO_MODEL:
            continue
        r = mine.get(n) or {}
        yes = decision_yes(r.get("decision"))
        v = {"n": n, "title": meta.get("title") or read_vacancy(path)[1].get("title", ""),
             "company": meta.get("company", ""), "flag": n in flags, "note": read_note(result),
             "model_score": meta.get("score"), "model_decision": meta.get("decision", ""),
             "model_yes": decision_yes(meta.get("decision"))}
        if yes is None:
            unrated.append(v)
            continue
        v.update(score=r["score"], can=r.get("can"), want=r.get("want"), decision=ratings.decision_word(r["decision"]),
                 yes=yes, date=r.get("date", ""), reason=r.get("reason", ""))
        v["diverge"] = diverges(v)
        rated.append(v)
    rated.sort(key=lambda v: v["date"] or "", reverse=True)        # без даты (старые оценки) — в конце
    unrated.sort(key=lambda v: not v["flag"])                      # с флагом ⚑ — первыми, дальше новые
    return rated, unrated


def picked(profile, rated=None):
    """Набор для автонастройки: подобранный программой без убранных вами и с добавленными."""
    rated = vacancies(profile)[0] if rated is None else rated
    data, known = read(profile), {v["n"] for v in rated}
    excluded, added = set(data.get("excluded", [])), set(data.get("added", [])) & known
    base = suggest([v for v in rated if v["n"] not in excluded], limit(profile))
    return base + [v["n"] for v in rated if v["n"] in added and v["n"] not in base]


def choose(profile, n, on):
    """Флажок в списке: убрать вакансию из набора или добавить в него."""
    data = read(profile)
    excluded, added = set(data.get("excluded", [])), set(data.get("added", []))
    (excluded.discard if on else excluded.add)(n)
    (added.add if on else added.discard)(n)
    write_json(profile.dir / FILE, {**data, "excluded": sorted(excluded), "added": sorted(added)})


def reset(profile):
    """«Подобрать заново»: забыть ваши правки набора."""
    data = read(profile)
    data.pop("excluded", None)
    data.pop("added", None)
    write_json(profile.dir / FILE, data)


def state(profile):
    """Окно калибровки: оценённые вакансии с отметкой «расходится», набор, предел, ещё не оценённые
    и итог последней автонастройки."""
    rated, unrated = vacancies(profile)
    data = read(profile)
    return {"rated": rated, "unrated": unrated, "picked": picked(profile, rated), "suggested": suggest(rated, limit(profile)),
            "limit": limit(profile), "minimum": MINIMUM, "edited": bool(data.get("excluded") or data.get("added")),
            "tune": read_json(profile.dir / tune.TUNE_DIR_NAME / "итог.json")}
