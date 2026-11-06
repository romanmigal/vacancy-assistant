"""История демо-профиля для скриншотов и видео: за три недели (16.10–06.11.2026) — даты добавления и разбора,
свои оценки (расхождение с моделью уменьшается к третьей неделе), статусы, этапы откликов, версии критериев.
Профиль andrey (вымышленный) должен быть уже создан, вакансии скачаны и разобраны.
Повторный запуск пересобирает всё с нуля.

Запуск из папки проекта:
    VACANCY_ASSISTANT_HOME="/Users/Shared/Помощник по вакансиям" python3 "dev/демо-история.py"
"""
import json
import random
import re
import sys
from pathlib import Path
from datetime import date, datetime, time, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from vacancy_assistant import funnel, ratings, summary
from vacancy_assistant.files import numbered_files, read_meta, read_prop, set_prop
from vacancy_assistant.profile import Profile
from vacancy_assistant.textio import read_json, read_text, write_json, write_text

random.seed(7)
p = Profile("andrey")
START, END = date(2026, 10, 16), date(2026, 11, 6)
DAYS = (END - START).days


def at(d, h0=9, h1=21):
    return datetime.combine(d, time(random.randint(h0, h1 - 1), random.randint(0, 59), random.randint(0, 59)))


def ru(d):
    return d.strftime("%d.%m.%Y")


files = numbered_files(p.vacancies)
ns = sorted(files)
# 1. Дата добавления: номера по порядку, от 16.10 до 06.11; в рабочие дни — чаще
days = [START + timedelta(days=i) for i in range(DAYS + 1)]
weights = [0.3 if d.weekday() >= 5 else random.choice([0.6, 1, 1.5, 2.5]) for d in days]
picked = sorted(random.choices(days, weights, k=len(ns) - 2) + [START, END])
saved = dict(zip(ns, picked))
for n in ns:                                               # повторный запуск — этапы и статусы с чистого листа
    r = p.results / files[n].name
    if r.exists():
        for prop in (*funnel.PROPS, funnel.STATUS_PROP):
            if read_prop(r, prop):
                set_prop(r, prop, "")

for n in ns:
    f = files[n]
    t = read_text(f)
    t = re.sub(r"(\*\*Сохранено:\*\* )\d{2}\.\d{2}\.\d{4}", lambda m: m[1] + ru(saved[n]), t)
    m = re.search(r"\*\*Опубликовано:\*\* (\d{2})\.(\d{2})\.(\d{4})", t)
    if m and date(int(m[3]), int(m[2]), int(m[1])) > saved[n]:          # опубликована не позже, чем сохранили
        posted = saved[n] - timedelta(days=random.randint(0, 3))
        t = t.replace(m[0], f"**Опубликовано:** {ru(posted)}")
    write_text(f, t)

# 2. Дата разбора — в день добавления (иногда на следующий)
scored = {}
hist = read_json(p.dir / funnel.ANALYSES_FILE) if (p.dir / funnel.ANALYSES_FILE).exists() else {}
for n in ns:
    r = p.results / files[n].name
    if not r.exists():
        continue
    d = min(saved[n] + timedelta(days=random.choice([0, 0, 0, 1])), END)
    scored[n] = d
    t = read_text(r)
    first, rest = t.split("\n", 1) if t.startswith("<!--") else ("", t)
    lines = t.split("\n")
    for i, line in enumerate(lines[:8]):
        if line.startswith("<!-- {"):
            meta = json.loads(line[5:-4])
            meta["date"], meta["saved"] = d.isoformat(), ru(saved[n])
            lines[i] = "<!-- " + json.dumps(meta, ensure_ascii=False) + " -->"
    write_text(r, "\n".join(lines))
    for e in hist.get(r.stem, []):
        e["date"], e["time"] = d.isoformat(), at(d).strftime("%H:%M:%S")
write_json(p.dir / funnel.ANALYSES_FILE, hist)

# 3. Свои оценки: ~70% разобранных, через 0–2 дня после разбора; расхождение с моделью уменьшается со временем
write_text(p.ratings, ratings.RATINGS_HEADER)
write_json(p.dir / funnel.RATINGS_FILE, {})
REASONS = {"да": ["подходит по стеку и уровню", "продуктовая компания, микросервисы", "сильная команда, хорошая вилка"],
           "возможно": ["вилка не указана", "много легаси, но есть развитие", "гибрид 3 дня в офисе"],
           "нет": ["низкая зарплата", "другой стек", "роль без разработки", "только аутстафф", "уровень ниже"]}
rated = {}
for n in ns:
    if n not in scored or random.random() > 0.7:
        continue
    meta = read_meta(p.results / files[n].name)
    week = (scored[n] - START).days // 7                    # 0, 1, 2 — к третьей неделе модель ближе к вам
    spread = [3, 2, 1][min(week, 2)]
    can = max(1, min(10, (meta.get("can") or 5) + random.randint(-spread, spread)))
    want = max(1, min(10, (meta.get("want") or 5) + random.randint(-spread, spread)))
    score = ratings.total(can, want, "да")
    decision = "да" if score >= 7 else "возможно" if score >= 5 else "нет"
    if random.random() < [0.35, 0.2, 0.08][min(week, 2)]:   # раньше — чаще не согласен с решением модели
        decision = random.choice([x for x in ("да", "возможно", "нет") if x != decision])
    d = min(scored[n] + timedelta(days=random.choice([0, 0, 1, 2])), END)
    ratings.set_rating(p, n, can, want, decision, random.choice(REASONS[decision]), today=d, when=at(d))
    rated[n] = (decision, d)

# 4. Статусы и этапы: откликнулся на часть «да», дальше — ответы, интервью, отказы, молчание
status = {n: "new" for n in ns}
for n in ns:
    summary.set_status(p, f"s{n}", "new")
yes = [n for n, (dec, _) in rated.items() if dec == "да"]
maybe = [n for n, (dec, _) in rated.items() if dec == "возможно"]
random.shuffle(yes)
random.shuffle(maybe)
applied = (yes + maybe[:max(0, 12 - len(yes))])[:14]          # на «да» — всегда, добираем «возможно»
no = [n for n, (dec, _) in rated.items() if dec == "нет"]
for n in no:
    r = p.results / files[n].name
    summary.set_status(p, f"s{n}", "no")
    funnel.record_status(r, "no", at(rated[n][1]), p)

# Пути по воронке: (этап, через сколько дней после предыдущего)
PATHS = [[("applied", 0), ("answered", 2), ("hr", 3), ("manager", 4), ("final", 5)],
         [("applied", 0), ("answered", 3), ("hr", 2), ("manager", 5)],
         [("applied", 1), ("answered", 2), ("hr", 4)],
         [("applied", 0), ("answered", 1), ("hr", 3), ("rejected", 4)],
         [("applied", 0), ("answered", 4), ("rejected", 2)],
         [("applied", 1), ("answered", 2)],
         [("applied", 0), ("answered", 5)],
         [("applied", 0), ("rejected", 3)],
         [("applied", 1), ("silent", 10)],
         [("applied", 0), ("silent", 9)],
         [("applied", 0)], [("applied", 1)], [("applied", 0)], [("applied", 0)]]
for n, path in zip(applied, PATHS):
    r = p.results / files[n].name
    d = rated[n][1]
    sec = "new"
    for stage, gap in path:
        d = d + timedelta(days=gap)
        if d > END:
            break
        _, section, _ = funnel.set_stage(r, stage, at(d), sec)
        if section:
            summary.set_status(p, f"s{n}", section)
            funnel.record_status(r, section, at(d, 21, 22), p)
            sec = section
    if sec == "interview" and path[-1][0] == "rejected":
        pass                                               # отказ после интервью — остаётся в «Интервью», как в жизни

# 5. Версии критериев: опросник — в начале, калибровка — в конце второй недели
idx = p.dir / "история критериев" / "версии.json"
if idx.exists():
    items = read_json(idx)
    for item, d in zip(items, ["2026-10-16", "2026-10-28"]):
        item["date"] = d
        for m in item.get("measures", []):
            m["date"] = d
    write_json(idx, items)

print(f"вакансий {len(ns)}, разобрано {len(scored)}, своих оценок {len(rated)}, откликов {len(applied)}")
