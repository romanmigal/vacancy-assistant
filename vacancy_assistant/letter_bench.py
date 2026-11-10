"""Эталон писем: сравнение версий промпта сопроводительного письма на письмах человека — для разработки.

Эталон — вакансии профиля, к которым человек сам поправил письмо модели или написал своё (source edit/own
в паспорте письма; из версий одной вакансии берётся отправленная, иначе последняя). Для каждой такой вакансии
программа пишет письмо каждой версией промпта и каждой моделью — без сохранения, файлы профиля не меняются —
и считает показатели без модели: длину, список «—», рамку (готовность, завершение, подпись), числа и названия,
которых нет ни в резюме с «Дополнительно о себе», ни в вакансии, повтор фраз между письмами и близость
к письму человека по словам. Отчёт — таблица сравнения и письма рядом с письмом человека.

Личные письма в репозиторий не попадают: эталон читается из профиля, отчёт пишется в профили/<имя>/настройка/.

    python3 razbor.py --profile ИМЯ letter-bench [ПРОМПТ…] [--models local,cloud] [--only 128,130] [--example ФАЙЛ] [--out ФАЙЛ]

ПРОМПТ — файл из шаблоны/ («письмо v2.txt» или коротко «v2») или путь; без них — две последние версии.
--example — образец письма из файла вместо шаблона профиля по умолчанию: проверить, что письмо повторяет
форму образца (абзац-обзор или список).
"""
import re
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

from . import cloud, letter_frame, letter_samples, letter_templates, settings
from .analysis import HISTORY, SOURCES
from .errors import AssistantError
from .files import read_meta, read_vacancy, strengths, vacancy_number
from .model import ask_local
from .profile import TEXT_FACTS_HEAD, letter_length
from .textio import read_text, write_text

REPORT = "Эталон писем.md"
SHINGLE = 5                       # повтор между письмами — общие отрезки из стольких слов подряд
WORD = re.compile(r"[a-zа-яё0-9]+", re.I)


# ---------- эталон ----------

def _letter(path):
    """(паспорт, текст письма без заголовка) файла письма."""
    text = read_text(path)
    return read_meta(path) or {}, (text.split("\n---\n", 1)[1] if "\n---\n" in text else text).strip()


def reference(profile, only=None):
    """Вакансии эталона: [{number, name, title, source, sent, human, vacancy, analysis}], по номеру."""
    names = {f.name for f in profile.letters.glob("*.md")}
    if (profile.letters / HISTORY).exists():
        names |= {d.name + ".md" for d in (profile.letters / HISTORY).iterdir() if d.is_dir()}
    items = []
    for name in names:
        number = vacancy_number(Path(name))
        if only and number not in only:
            continue
        files = [profile.letters / name] + sorted((profile.letters / HISTORY / name[:-3]).glob("*.md"), reverse=True)
        own = [(m, t) for m, t in map(_letter, (f for f in files if f.exists())) if m.get("source") in SOURCES]
        analysis, vacancy = profile.results / name, profile.vacancies / name
        if not own or not analysis.exists() or not vacancy.exists():
            continue
        meta, human = next(((m, t) for m, t in own if m.get("sent")), own[0])
        info = read_meta(analysis) or {}
        items.append({"number": number, "name": name, "role": info.get("title", ""),
                      "title": f"{info.get('title', '')} — {info.get('company', '')}",
                      "source": meta["source"], "sent": meta.get("sent", ""), "human": human,
                      "vacancy": read_vacancy(vacancy)[0], "analysis": analysis})
    return sorted(items, key=lambda x: x["number"] or 0)


def prompt_files(names):
    """Файлы промпта по именам: путь, имя в шаблоны/ или «v2»; без имён — две последние версии «письмо v*.txt»."""
    if not names:
        found = sorted(settings.TEMPLATES.glob("письмо v*.txt"), key=lambda f: int(re.sub(r"\D", "", f.stem) or 0))
        return found[-2:]
    files = []
    for n in names:
        n = f"письмо {n}" if re.fullmatch(r"v\d+", n) else n
        f = Path(n) if Path(n).exists() else settings.TEMPLATES / (n if n.endswith(".txt") else n + ".txt")
        if not f.exists():
            raise AssistantError(f"Нет файла промпта «{n}» — ни пути, ни такого шаблона в {settings.TEMPLATES.name}/.")
        files.append(f)
    return files


def framed(template):
    """Промпт, где модель пишет только середину, а рамку ставит программа (v3 и дальше): в нём нет подписи."""
    return "{signature}" not in read_text(template)


# ---------- письмо без сохранения ----------

def generate(profile, item, template, ask, resume, example):
    """Письмо для вакансии эталона этой версией промпта по образцу example — как пишет программа, но без файла.
    Свои отправленные письма — образцы, кроме писем к этой же вакансии: как у нового отклика. (письмо, секунд)."""
    samples = letter_samples.pick(profile, item["name"], item["role"])
    if framed(template):
        greeting, middle = letter_frame.split_example(example, profile)
        prompt = profile.letter_prompt(resume, item["vacancy"], strengths(read_text(item["analysis"])), middle, template,
                                       samples)
    else:                                           # старые промпты: всё письмо целиком пишет модель
        prompt = profile.letter_prompt(resume, item["vacancy"], strengths(read_text(item["analysis"])), example, template)
    start = time.time()
    raw = ask(prompt, settings.LETTER_MODEL, settings.LETTER_OPTIONS)
    seconds = round(time.time() - start)
    if framed(template):
        return letter_frame.assemble(profile, greeting, letter_frame.strip_frame(raw, profile)), seconds
    return raw.strip(), seconds


def models(profile, wanted):
    """{название модели: ask} — local (Ollama) и cloud (если в профиле выбран GigaChat и есть ключ)."""
    found = {}
    if "local" in wanted:
        found[settings.LETTER_MODEL] = lambda p, m, o: ask_local(p, m, o)
    if "cloud" in wanted and cloud.active(profile):
        found[cloud.model_name(profile)] = lambda p, m, o: cloud.ask(p, o)
    if not found:
        raise AssistantError("Нет ни одной модели для сравнения: local — Ollama, cloud — GigaChat, выбранный в профиле.")
    return found


# ---------- показатели без модели ----------

def words(text):
    return WORD.findall((text or "").lower())


def stems(text):
    """Грубые основы слов — без окончания: «банке» и «банка», «руководил» и «руководила» совпадают."""
    return {w[:5] if len(w) > 6 else w[:-1] if len(w) > 4 else w for w in words(text) if len(w) >= 4 and not w.isdigit()}


def closeness(a, b):
    """Близость двух текстов по словам (Жаккар по основам), 0–1."""
    x, y = stems(a), stems(b)
    return len(x & y) / len(x | y) if x | y else 0.0


def has_list(text):
    return any(re.match(r"\s*(?:—|-|•)\s", line) for line in (text or "").split("\n"))


def frame_score(letter, profile):
    """Сколько фраз рамки из профиля есть в письме: (есть, всего) — готовность (если задана), завершение, подпись."""
    phrases = [x for x in letter_frame._settings(profile) if x]
    return sum(x in letter for x in phrases), len(phrases)


NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
NAME = re.compile(r"«[^»\n]{2,40}»|[A-Za-z][A-Za-z0-9&+.-]*|[А-ЯЁ][а-яёА-ЯЁ-]{2,}")


def names(text):
    """Названия в тексте: в кавычках «…», латиницей с заглавной (SAP, Kubernetes) и русские слова с заглавной
    не в начале предложения или пункта."""
    for m in NAME.finditer(text):
        tok = m.group(0).rstrip(".-")
        if tok.startswith("«"):
            yield tok.strip("«»")
        elif tok[0].isascii():
            if any(c.isupper() for c in tok):
                yield tok
        else:
            before = text[:m.start()].rstrip(" \t")
            if before and before[-1] not in ".!?:—-•\n«(\"":
                yield tok


def unsupported(text, source):
    """Числа (от 10) и названия из письма, которых нет в источнике (резюме, «о себе», вакансия): [строка]."""
    numbers = {n.replace(",", ".") for n in NUMBER.findall(source)}
    known, low, found = stems(source), source.lower(), []
    for n in NUMBER.findall(text):
        if float(n.replace(",", ".")) >= 10 and n.replace(",", ".") not in numbers:
            found.append(n)
    for name in names(text):
        s = stems(name)
        if not (s <= known if s else name.lower() in low):
            found.append(name)
    return list(dict.fromkeys(found))


def shingles(text):
    w = words(text)
    return {" ".join(w[i:i + SHINGLE]) for i in range(len(w) - SHINGLE + 1)}


def repeats(texts):
    """Повтор между письмами одной версии: доля отрезков письма, которые есть и в другом письме (средняя, 0–1),
    и самые частые повторы целыми фразами [(фраза, в скольких письмах)] — те, что в половине писем и чаще."""
    sets = [shingles(t) for t in texts]
    counts = Counter(s for x in sets for s in x)
    shares = [sum(counts[s] > 1 for s in x) / len(x) for x in sets if x]
    found = {}
    for t in texts:                                 # подряд идущие общие отрезки письма — одна фраза
        w, run = words(t), []
        for i in range(len(w) - SHINGLE + 2):
            c = counts.get(" ".join(w[i:i + SHINGLE]), 0) if i <= len(w) - SHINGLE else 0
            if c > 1 and c * 2 >= len(texts):
                run.append((i, c))
            elif run:
                phrase = " ".join(w[run[0][0]:run[-1][0] + SHINGLE])
                found[phrase] = max(found.get(phrase, 0), min(c for _, c in run))
                run = []
    common = sorted(found.items(), key=lambda x: (-x[1], -len(x[0])))
    return (sum(shares) / len(shares) if shares else 0.0), [(s, c) for s, c in common
                                                            if not any(s != o and s in o for o, _ in common)][:3]


# ---------- прогон и отчёт ----------

def run(profile, names=(), wanted=("local", "cloud"), only=None, out=None, log=None, asks=None, example=None):
    """Прогон эталона: пишет отчёт, возвращает его файл. example — файл образца письма вместо шаблона профиля,
    asks — {модель: ask} вместо настоящих (тесты)."""
    log = log or (lambda text: print(text, flush=True))      # ход прогона виден и при выводе в файл
    items = reference(profile, only)
    if not items:
        raise AssistantError("Эталона нет: в профиле нет вакансий со своим или поправленным письмом и разбором.")
    templates, asks = prompt_files(list(names)), asks or models(profile, wanted)
    resume = profile.read_resume()
    sample = (read_text(example).strip(), Path(example).name) if example else \
        (letter_templates.get(profile)["text"], f"шаблон «{letter_templates.get(profile)['name']}»")
    source = profile.with_facts(resume, TEXT_FACTS_HEAD)
    results = {}                                    # (промпт, модель) → [{item, letter, seconds, error}]
    for t in templates:
        for model, ask in asks.items():
            for item in items:
                log(f"{t.stem} · {model} · {item['number']}")
                try:
                    letter, seconds = generate(profile, item, t, ask, resume, sample[0])
                    row = {"letter": letter, "seconds": seconds}
                except Exception as e:              # noqa: BLE001 — модель не ответила: в отчёт, прогон идёт дальше
                    row = {"error": str(e) or type(e).__name__}
                results.setdefault((t.stem, model), []).append({"item": item, **row})
    path = Path(out) if out else profile.dir / "настройка" / REPORT
    path.parent.mkdir(parents=True, exist_ok=True)
    write_text(path, report(profile, items, results, source, sample))
    log(f"Отчёт: {path}")
    return path


def measure(row, profile, source, length):
    """Показатели письма: знаки, длина середины как у образца, список, рамка, факты не из источника,
    близость к письму человека."""
    letter, item = row["letter"], row["item"]
    middle = letter_frame.strip_frame(letter, profile)
    got, total = frame_score(letter, profile)
    return {"chars": len(letter), "fits": length[0] <= len(middle) <= length[1], "list": has_list(middle),
            "frame": (got, total),
            "facts": unsupported(middle, source + "\n" + item["vacancy"]),
            "close": closeness(middle, letter_frame.strip_frame(item["human"], profile))}


def _pct(x):
    return f"{round(x * 100)}%"


def report(profile, items, results, source, sample):
    lines = [f"# Эталон писем — сравнение промптов", "",
             f"Профиль: {profile.name} · {datetime.now():%d.%m.%Y %H:%M} · вакансий в эталоне: {len(items)} · "
             f"образец письма: {sample[1]}", "",
             "Показатели без модели. **Длина как у образца** — основная часть письма (без рамки) в пределах ± 20% от образца. **Рамка** — сколько фраз из профиля (готовность, завершение, подпись) есть в письме. "
             "**Не из резюме** — числа и названия, которых нет ни в резюме с «Дополнительно о себе», ни в вакансии "
             "(проверять глазами: это кандидаты в выдумку). **Повтор** — доля фраз письма, которые есть и в других письмах "
             "той же версии. **Близость** — общие слова с письмом человека.", "",
             "## Сводка", "",
             "| Промпт | Модель | Писем | Знаков, ср. | Длина как у образца | Со списком «—» | Рамка | Не из резюме, на письмо | "
             "Повтор | Близость | Секунд, ср. |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    length = letter_length(letter_frame.strip_frame(sample[0], profile))
    humans = [x["human"] for x in items]
    rep, _ = repeats([letter_frame.strip_frame(h, profile) for h in humans])
    lines.append(f"| человек | — | {len(items)} | {round(sum(map(len, humans)) / len(humans))} | "
                 f"{sum(length[0] <= len(letter_frame.strip_frame(h, profile)) <= length[1] for h in humans)} | {sum(has_list(h) for h in humans)} | — | — | {_pct(rep)} | — | — |")
    measured, phrases = {}, {}
    for (prompt, model), rows in results.items():
        ok = [r for r in rows if "letter" in r]
        m = measured[(prompt, model)] = {id(r): measure(r, profile, source, length) for r in ok}
        if not ok:
            lines.append(f"| {prompt} | {model} | 0 из {len(rows)} | — | — | — | — | — | — | — | — |")
            continue
        vals = list(m.values())
        rep, phrases[(prompt, model)] = repeats([letter_frame.strip_frame(r["letter"], profile) for r in ok])
        got, total = sum(v["frame"][0] for v in vals), sum(v["frame"][1] for v in vals)
        lines.append(f"| {prompt} | {model} | {len(ok)}{'' if len(ok) == len(rows) else f' из {len(rows)}'} | "
                     f"{round(sum(v['chars'] for v in vals) / len(vals))} | {sum(v['fits'] for v in vals)} | "
                     f"{sum(v['list'] for v in vals)} | {_pct(got / total) if total else '—'} | "
                     f"{sum(len(v['facts']) for v in vals) / len(vals):.1f} | {_pct(rep)} | "
                     f"{_pct(sum(v['close'] for v in vals) / len(vals))} | {round(sum(r['seconds'] for r in ok) / len(ok))} |")
    if any(phrases.values()):
        lines += ["", "### Фразы, которые повторяются в половине писем и чаще", ""]
        for (prompt, model), common in phrases.items():
            for phrase, count in common:
                lines.append(f"- {prompt} · {model}: «…{phrase}…» — {count} из {len(results[(prompt, model)])}")
    lines += ["", "## По вакансиям"]
    for item in items:
        how = "своё письмо" if item["source"] == "own" else "правка письма модели"
        sent = f", отправлено {item['sent']}" if item["sent"] else ""
        lines += ["", f"### {item['number']} {item['title']}", "", f"**Человек** ({how}{sent}) — {len(item['human'])} знаков", "",
                  _quote(item["human"])]
        for (prompt, model), rows in results.items():
            row = next(r for r in rows if r["item"] is item)
            if "error" in row:
                lines += ["", f"**{prompt} · {model}** — ошибка: {row['error']}"]
                continue
            v = measured[(prompt, model)][id(row)]
            got, total = v["frame"]
            facts = ", ".join(f"«{x}»" for x in v["facts"]) or "нет"
            lines += ["", f"**{prompt} · {model}** — {v['chars']} знаков · {'список' if v['list'] else 'без списка'} · "
                          f"рамка {got}/{total} · близость {_pct(v['close'])} · {row['seconds']} с · не из резюме: {facts}",
                      "", _quote(row["letter"])]
    return "\n".join(lines) + "\n"


def _quote(text):
    return "\n".join(f"> {line}" if line else ">" for line in text.strip().split("\n"))


def parse_args(args):
    """Аргументы команды: (промпты, модели, номера, файл отчёта, файл образца)."""
    names, wanted, only, out, example = [], ("local", "cloud"), None, None, None
    it = iter(args)
    for a in it:
        if a == "--models":
            wanted = tuple(x.strip() for x in next(it, "").split(",") if x.strip())
        elif a == "--only":
            only = {int(x) for x in re.findall(r"\d+", next(it, ""))}
        elif a == "--example":
            example = next(it, None)
        elif a == "--out":
            out = next(it, None)
        else:
            names.append(a)
    return names, wanted, only, out, example

