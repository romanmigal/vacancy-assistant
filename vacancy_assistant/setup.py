"""Мастер первого запуска: проверка компьютера, скачивание модели, профиль из анкеты.

Анкета — простые вопросы (кем работать, где, от какой зарплаты, что важно). Из ответов собираются
профиль.json, критерии.txt, поиски.txt и образец письма — те же файлы, что раньше заполнялись руками.
Критерии получаются базовыми; точнее их настраивают потом по своим оценкам (ratings → tune).
"""
import json
import os
import platform
import re
import shutil
import time
from pathlib import Path
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from datetime import date

from . import mask, settings
from .errors import AssistantError
from .hh import phase
from .profile import ANSWERS_FILE, CONFIG_FILE, Profile
from .textio import log_print, read_json, read_text, write_json, write_text

OLLAMA_BASE = settings.OLLAMA.split("/api/")[0]
MIN_MEMORY_GB = 16              # gemma4:12b в памяти — около 8 ГБ, плюс система и браузер
MODEL_SIZE_GB = 8

# Регионы hh.ru: название → код area в адресе поиска
AREAS = {"Москва": 1, "Санкт-Петербург": 2, "Екатеринбург": 3, "Новосибирск": 4, "Нижний Новгород": 66,
         "Казань": 88, "Краснодар": 53, "Самара": 78, "Ростов-на-Дону": 76, "Владивосток": 22}
REMOTE = ("удалённо", "area=113&work_format=REMOTE")

START = {"сразу": "Могу приступить сразу.", "2 недели": "Могу приступить через две недели.",
         "месяц": "Могу приступить через месяц.", "не писать": ""}     # «не писать» — письмо без фразы о готовности

VACANCY_ROOM = 8000      # знаков вакансии, которые должны помещаться в окно модели вместе с резюме (обычная — 3–6 тыс.)


def resume_room():
    """Сколько знаков резюме с «Дополнительно о себе» и критериями помещается в промпт разбора так, чтобы
    рядом влезла вакансия на VACANCY_ROOM знаков; длиннее — в мастере предупреждение, а у длинных вакансий
    программа обрежет конец текста."""
    return settings.prompt_room(settings.OPTIONS) - len(read_text(settings.ANALYSIS_TEMPLATE)) - VACANCY_ROOM


LETTER_TEMPLATE = """Здравствуйте!

Откликаюсь на позицию «{title}». Мне близка задача, которую вы описываете: [одна фраза о главной задаче вакансии].

Похожие задачи я {solved} раньше:
— в [компания] [что {did}] — [результат с цифрой];
— в [компания] [что {did}] — [результат с цифрой].

{start}

{closing}

{name}
"""


# ---------- проверка компьютера ----------

AREA_SUGGEST = "https://api.hh.ru/suggests/areas?text="   # открытый справочник hh: город → код, без ключа


def find_area(name, fetch_json=None):
    """Город по названию → {"id": "92", "name": "Тула", "region": "Тульская область"} или None.
    Сначала точное совпадение названия, иначе первая подсказка hh."""
    name = (name or "").strip()
    if not name:
        return None
    if name in AREAS:
        return {"id": str(AREAS[name]), "name": name, "region": ""}
    if fetch_json is None:
        def fetch_json(url):
            request = urllib.request.Request(url, headers={"User-Agent": settings.USER_AGENT})
            with urllib.request.urlopen(request, timeout=15) as r:
                return json.load(r)
    try:
        items = fetch_json(AREA_SUGGEST + urllib.parse.quote(name)).get("items", [])
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise AssistantError("Не удалось проверить город на hh.ru — нет связи (включён VPN?).") from e
    if not items:
        return None
    best = next((i for i in items if i["text"].lower() == name.lower()), items[0])
    return {"id": best["id"], "name": best["text"], "region": (best.get("parent") or {}).get("text", "")}


def memory_gb():
    """Объём оперативной памяти в ГБ (None — если узнать не удалось)."""
    try:
        if platform.system() == "Darwin":
            return int(subprocess.check_output(["sysctl", "-n", "hw.memsize"], timeout=5)) / 2**30
        if platform.system() == "Windows":
            import ctypes

            class MemoryStatus(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            status = MemoryStatus()
            status.dwLength = ctypes.sizeof(status)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
            return status.ullTotalPhys / 2**30
        with open("/proc/meminfo") as f:
            return int(re.search(r"MemTotal:\s+(\d+)", f.read()).group(1)) / 2**20
    except Exception:                                   # noqa: BLE001 — не критично, просто не покажем
        return None


def ollama_models():
    """Модели в Ollama или None, если Ollama не запущена."""
    try:
        with urllib.request.urlopen(OLLAMA_BASE + "/api/tags", timeout=3) as r:
            return [m["name"] for m in json.load(r).get("models", [])]
    except (urllib.error.URLError, OSError, ValueError):
        return None


def ollama_installed():
    """Установлена ли Ollama (даже если сейчас не запущена): команда в PATH или приложение на обычном месте."""
    places = [Path("/Applications/Ollama.app"), Path.home() / "Applications/Ollama.app",
              Path("/opt/homebrew/bin/ollama"), Path("/usr/local/bin/ollama"),
              Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Ollama/ollama.exe"]
    return bool(shutil.which("ollama")) or any(p.exists() for p in places)


def check_computer():
    """Что есть и чего не хватает: память, место на диске, Ollama, модель."""
    memory = memory_gb()
    free = shutil.disk_usage(settings.data_root()).free / 2**30
    models = ollama_models()
    return {
        "system": {"Darwin": "macOS", "Windows": "Windows"}.get(platform.system(), platform.system()),
        "memory_gb": round(memory, 1) if memory else None,
        "memory_ok": memory is None or memory >= MIN_MEMORY_GB - 0.5,
        "min_memory_gb": MIN_MEMORY_GB,
        "disk_free_gb": round(free, 1),
        "disk_ok": free >= MODEL_SIZE_GB + 2,
        "ollama": models is not None,
        "ollama_installed": models is not None or ollama_installed(),
        "model": settings.MODEL,
        "model_size_gb": MODEL_SIZE_GB,
        "model_ok": bool(models) and settings.MODEL in models,
    }


def pull_model(log=None, model=settings.MODEL, clock=time.monotonic):
    """Скачивает модель через Ollama и показывает ход: процент по всей модели (все её части вместе)
    каждые 5% и не реже раза в 15 секунд — со скоростью и оставшимся временем, чтобы было видно, что
    загрузка идёт. Ollama присылает ход по каждой части отдельно; раньше маленькая часть, дошедшая
    до 100%, «съедала» вывод, и большая (8 ГБ) качалась молча — казалось, что программа зависла."""
    log = log or log_print
    phase(log, f"Скачиваю модель {model} (около {MODEL_SIZE_GB} ГБ)")
    request = urllib.request.Request(OLLAMA_BASE + "/api/pull", json.dumps({"model": model, "stream": True}).encode(),
                                     {"Content-Type": "application/json"})
    parts, shown, started = {}, -5, clock()
    last_time, last_done = started, 0
    try:
        with urllib.request.urlopen(request, timeout=600) as r:
            for line in r:
                if not line.strip():
                    continue
                item = json.loads(line)
                if item.get("error"):
                    raise AssistantError(f"Ollama не скачала модель: {item['error']}")
                if item.get("digest") and item.get("total"):
                    parts[item["digest"]] = (item.get("completed") or 0, item["total"])
                    done, total = sum(c for c, _ in parts.values()), sum(t for _, t in parts.values())
                    if total < 100 * 2**20:
                        continue                               # пока видны только мелкие части — процент бессмыслен
                    pct, now = int(done * 100 / total), clock()
                    if pct >= shown + 5 or now - last_time >= 15:
                        speed = (done - last_done) / max(now - last_time, 0.001)
                        left = f", осталось около {int((total - done) / speed / 60) + 1} мин" if speed > 0 and done < total else ""
                        log(f"{pct}% — {done / 2**30:.1f} из {total / 2**30:.1f} ГБ"
                            + (f", {speed / 2**20:.1f} МБ/с{left}" if speed >= 0.1 * 2**20 else ""))
                        shown, last_time, last_done = max(shown, pct - pct % 5), now, done
                elif item.get("status") and not item.get("digest"):
                    status = item["status"]
                    log({"verifying sha256 digest": "Проверяю скачанное — это может занять пару минут…",
                         "writing manifest": "Записываю модель…", "success": "Готово.",
                         "pulling manifest": "Узнаю, из чего состоит модель…"}.get(status, status))
    except urllib.error.URLError as e:
        raise AssistantError("Ollama не запущена или нет интернета. Запустите Ollama и повторите.") from e
    log("Модель скачана.")


# ---------- профиль из анкеты ----------

TRANSLIT = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
                    ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r", "s",
                     "t", "u", "f", "h", "ts", "ch", "sh", "sch", "", "y", "", "e", "yu", "ya"]))


def profile_id(name, existing=()):
    """«Мария Иванова» → «mariya»; если занято — mariya2, mariya3…  (имя папки без кириллицы и пробелов)."""
    first = (name.strip().split() or ["profile"])[0].lower()
    slug = re.sub(r"[^a-z0-9]", "", "".join(TRANSLIT.get(ch, ch) for ch in first)) or "profile"
    candidate, i = slug, 2
    while candidate in existing:
        candidate, i = f"{slug}{i}", i + 1
    return candidate


def lines(text):
    return [l.strip(" •-—\t") for l in (text or "").splitlines() if l.strip(" •-—\t")]


# Слова уровня, которые есть в названиях разных профессий: «Финансовый директор» ищем по «финанс»,
# а не по «директор» — иначе пройдут и «Коммерческий директор», и «Технический директор».
# Зато уровень проверяем отдельно: «Главный бухгалтер» → в названии должно быть «главн»
LEVEL_WORDS = ("главн", "ведущ", "старш", "директ", "руковод", "начальн", "head", "chief", "senior", "lead",
               "cfo", "cio", "cto", "cmo", "coo", "ceo", "cdo", "hrd")
GENERIC_WORDS = ("младш", "заместит", "менеджер", "специалист", "отдел", "junior")
SKIP_WORDS = ("для", "and", "the", "по", "of", "на", "в")
# Для руководящих должностей — то, что почти всегда означает уровень ниже
SENIOR_STOP_WORDS = ["стажер", "стажёр", "ассистент", "помощник", "младш", "оператор", "кассир", "заместител"]


def stem(word):
    """Начало слова без окончания, чтобы находились падежи и формы: «финансовый» → «финанс»."""
    if len(word) > 6 and re.search(r"[а-яё]$", word):
        return word[:max(5, len(word) - 4)]
    return word


def title_words(titles):
    """Слова из желаемых должностей для отсева по названию.
    Возвращает (про профессию, про уровень): «Главный бухгалтер», «Финансовый директор» →
    (["бухга", "финанс"], ["главн", "директ"]). Уровень — только если он есть в каждой должности."""
    field, level, every_has_level = [], [], bool(titles)
    for t in titles:
        words = [w for w in re.findall(r"\w{2,}", t.lower()) if w not in SKIP_WORDS]
        lv = [w for w in words if w.startswith(LEVEL_WORDS)]
        specific = [stem(w) for w in words if not w.startswith(LEVEL_WORDS + GENERIC_WORDS)]
        every_has_level &= bool(lv)
        for w in specific or [stem(w) for w in words]:
            if w not in field:
                field.append(w)
        for w in lv:
            w = w if len(w) <= 3 else next(l for l in LEVEL_WORDS if w.startswith(l))
            if w not in level:
                level.append(w)
    return field, (level if every_has_level else [])


def split_words(words):
    """Короткие слова (ИТ, CFO) — только целиком, иначе «ит» найдётся внутри «кредит»; длинные — как начало слова."""
    return {"слова": [w for w in words if len(w) <= 3], "части": [w for w in words if len(w) > 3]}


def title_filter(a):
    """Слова для отсева по названию: из анкеты, если человек их правил, иначе — из должностей."""
    auto_field, auto_level = title_words(lines(a.get("titles")))
    given = lambda key, auto: lines(a[key]) if a.get(key) is not None else auto
    return (given("title_words", auto_field), given("level_words", auto_level),
            given("stop_words", SENIOR_STOP_WORDS if auto_level else []))


def build_criteria(a):
    """Базовые критерии из анкеты: локация, зарплата, должность, что не подходит; мягкие — что важно."""
    places = []
    if a.get("city"):
        formats = [f for f, on in (("офис", a.get("office")), ("гибрид", a.get("hybrid"))) if on]
        places.append(a["city"] + (f" ({' или '.join(formats)})" if formats else ""))
    if a.get("remote"):
        places.append("удалённо из любого города")
    hard = [f"Локация и формат: {' или '.join(places) or 'любые'}. Переезд в другой город — нет."]

    salary = int(re.sub(r"\D", "", str(a.get("salary") or "")) or 0)
    if salary:
        s = f"{salary:,}".replace(",", " ")
        rule = (f"Нарушение, если верхняя граница вилки («до») ниже {s} или указано только «от» ниже {s}. "
                "Если зарплата не указана — ❓, это не нарушение.")
        if a.get("part_time"):
            hard.append(f"Зарплата зависит от формата роли.\n"
                        f"  • Постоянная роль (полная занятость, в штат) — от {s} ₽ в месяц. {rule}\n"
                        f"  • Временная или проектная роль с частичной занятостью — зарплата может быть ниже {s}, "
                        "критерий не нарушен.\n"
                        "  • Если формат роли в вакансии не указан — считай её постоянной.")
        else:
            hard.append(f"Зарплата: от {s} ₽ в месяц. {rule}")

    titles = lines(a.get("titles"))
    if titles:
        hard.append(f"Должность: подходят роли {', '.join('«' + t + '»' for t in titles)} и близкие к ним "
                    "по смыслу и уровню. Роль заметно ниже по уровню или из другой профессии — нарушение.")
    for item in lines(a.get("not_ok")):
        hard.append(f"Не подходит: {item}. Нарушение, только если это основная часть роли.")

    text = "Жёсткие (если нарушен хотя бы один — вакансия мне не подходит):\n"
    text += "\n".join(f"К{i}. {c}" for i, c in enumerate(hard, 1))
    plus = lines(a.get("important"))
    if plus:
        text += "\n\nМягкие (не отсекают, но влияют на «Хочу»):\n" + ";\n".join(f"+ {p}" for p in plus) + "."
    return text + "\n"


def hh_auto(on, risk):
    """Настройка «hh_авто»: включить можно только вместе с согласием на риск; дата согласия — сегодня."""
    if on and not risk:
        raise AssistantError("Чтобы включить поиск на hh.ru, отметьте, что понимаете: это нарушает соглашение hh, "
                             "и вы принимаете риск.")
    return {"включено": True, "согласие": date.today().isoformat()} if on else {"включено": False}


def build_config(a, resume="резюме.md"):
    name = a["name"].strip()
    field = (a.get("field") or "").strip()
    where = []
    if a.get("city") in AREAS:
        where.append([a["city"], f"area={AREAS[a['city']]}"])
    elif a.get("city"):                                    # другой город — код из справочника hh
        area = a.get("city_area") or (find_area(a["city"]) or {}).get("id")
        if not area:
            raise AssistantError(f"Не нашёл город «{a['city']}» на hh.ru.")
        where.append([a["city"], f"area={area}"])
    if a.get("remote"):
        where.append(list(REMOTE))
    intro = ("Я ищу постоянную работу в штат, но рассматриваю и временные или проектные роли. "
             if a.get("part_time") else "Я ищу постоянную работу в штат. ")
    closing = "Буду рада обсудить детали." if a.get("female") else "Буду рад обсудить детали."
    field_words, level_words, stop_words = title_filter(a)
    return {
        "_пояснение": "Профиль создан мастером первого запуска. Пути — относительно этой папки.",
        "имя": name,
        "резюме": resume,
        "путь_в_obsidian": "",
        # поиск на hh.ru программой — только если человек включил его и принял риск (соглашение hh запрещает скрипты)
        "hh_авто": hh_auto(a.get("hh_auto"), a.get("hh_risk")),
        # ленты вакансий Хабр Карьеры и GeekJob — мастер предлагает их для ИТ
        "rss": {"habr": bool(a.get("rss_habr")), "geekjob": bool(a.get("rss_geekjob"))},
        # модель профиля: GigaChat — только если человек выбрал его в мастере и дал согласие
        "модель": ({"облако": False, "без_модели": True} if a.get("no_model") else
                   {"облако": True, "согласие": date.today().isoformat()} if a.get("cloud") else {"облако": False}),
        # что скрывать от GigaChat кроме личных данных: прошлых работодателей — по галочке на шаге «Резюме»
        "скрытие": {"компании": bool(a.get("cloud") and a.get("hide_firms"))},
        "разбор": {
            "для_кого": f"специалистов и руководителей в сфере «{field}»" if field else "специалистов и руководителей",
            "вступление": intro,
            "общий_навык": f"«опыт в своей сфере ({field})»" if field else "«опыт работы по профессии»",
            "модель_для_страниц": bool(a.get("llm_pages")),
        },
        "письмо": {
            "кому_помогаем": "соискателю",
            "готовность": START.get(a.get("start"), START["2 недели"]),
            "завершение": closing,
            "подпись": name,
            "минимальная_оценка": 7,
        },
        "поиск": {
            "где": where or [list(REMOTE)],
            "дней": 7,
            "название_про_сферу": split_words(field_words),
            "название_уровень": split_words(level_words),
            "стоп_слова": stop_words,
            # фильтр выдачи hh.ru по зарплате — шаг «Отбор при поиске»; при создании — из «Зарплата от» опросника
            "зарплата_от": int(re.sub(r"\D", "", str(a.get("search_salary") or "")) or 0) or None,
            "только_с_зарплатой": bool(a.get("search_salary_only")),
            "весь_текст": bool(a.get("search_full_text")),       # слова запроса на hh.ru — и в описании
        },
    }


def letter_sample(a):
    """Заготовка образца письма с подсказками в [скобках]."""
    config = build_config({"name": "", **a})
    titles = lines(a.get("titles"))
    text = LETTER_TEMPLATE.format(
        title=titles[0] if titles else "[должность]", solved="решала" if a.get("female") else "решал",
        did="сделала" if a.get("female") else "сделал", start=config["письмо"]["готовность"],
        closing=config["письмо"]["завершение"], name=(a.get("name") or "").strip() or "[имя]")
    return re.sub(r"\n{3,}", "\n\n", text)            # «не писать» о готовности — без пустого абзаца


def create_profile(a, profiles_dir=None, log=None):
    """Создаёт профиль из анкеты мастера. Возвращает имя папки профиля."""
    log = log or log_print
    if not (a.get("name") or "").strip():
        raise AssistantError("Укажите имя.")
    if not lines(a.get("titles")):
        raise AssistantError("Укажите хотя бы одну должность, которую ищете.")
    if not (a.get("resume") or "").strip():
        raise AssistantError("Добавьте резюме: загрузите выгрузку с hh.ru или вставьте текст.")
    hh_auto(a.get("hh_auto"), a.get("hh_risk"))
    root = profiles_dir or settings.profiles_dir()
    root.mkdir(parents=True, exist_ok=True)
    existing = {d.name for d in root.iterdir() if d.is_dir()}
    name = (a.get("profile_id") or "").strip()                 # имя профиля из мастера; пусто — из имени человека
    if name:
        if not re.fullmatch(r"[\w-]{1,40}", name):
            raise AssistantError("Имя профиля — буквы, цифры, «-» или «_», без пробелов (например, maria).")
        if name in existing:
            raise AssistantError(f"Профиль «{name}» уже есть — выберите другое имя.")
    else:
        name = profile_id(a["name"], existing)
    target = root / name
    target.mkdir()
    config = build_config(a)
    write_json(target / CONFIG_FILE, config)
    write_text(target / "резюме.md", a["resume"].strip() + "\n")
    if (a.get("facts") or "").strip():
        Profile(name, root).write_facts(a["facts"])
    write_text(target / "критерии.txt", (a.get("criteria") or "").strip() + "\n" if (a.get("criteria") or "").strip()
               else build_criteria(a))
    write_json(target / ANSWERS_FILE, {k: a.get(k) for k in ("office", "hybrid", "salary", "important", "not_ok", "field")})
    write_text(target / "поиски.txt", "# Поисковые запросы — по одному на строку. Строки с # — комментарии.\n\n"
               + "\n".join(lines(a.get("titles"))) + "\n")
    letter = (a.get("letter") or "").strip() or letter_sample(a)
    write_text(target / "образец письма.txt", letter.strip() + "\n")
    for d in ("vacancies", "разборы", "письма"):
        (target / d).mkdir()
    # Первый профиль становится профилем по умолчанию
    if not (root / settings.DEFAULT_PROFILE_FILE).exists():
        write_text(root / settings.DEFAULT_PROFILE_FILE, name + "\n")
    log(f"Создан профиль {target}")
    return name


# ---------- редактирование профиля ----------

# ANSWERS_FILE (из profile) — «анкета.json»: ответы мастера, которых нет в других файлах (зарплата, что важно…)


def answers_from_criteria(text):
    """Ответы опросника, восстановленные из критериев, которые собрал мастер: зарплата, «что важно»,
    «что не подходит», офис и гибрид. Нужно для профилей без анкеты (или с пустой анкетой)."""
    found = {}
    block = re.search(r"^К\d+\. Зарплата(.*?)(?=^К\d+\.|^\s*$|\Z)", text, re.M | re.S)   # и подпункты «•»
    m = block and re.search(r"от ([\d  ]+) ₽", block.group(1))
    if m:
        found["salary"] = re.sub(r"\D", "", m.group(1))
    not_ok = re.findall(r"^К\d+\. Не подходит: (.+?)\. Нарушение, только если", text, re.M)
    if not_ok:
        found["not_ok"] = "\n".join(not_ok)
    soft = text.split("Мягкие", 1)[1] if "Мягкие" in text else ""
    plus = [l[2:].strip().rstrip(";.") for l in soft.splitlines() if l.startswith("+ ")]
    if plus:
        found["important"] = "\n".join(plus)
    m = re.search(r"^К\d+\. Локация и формат: [^(\n]*\(([^)]*)\)", text, re.M)
    if m:
        found["office"], found["hybrid"] = "офис" in m.group(1), "гибрид" in m.group(1)
    return found


def answers_from_profile(p):
    """Ответы мастера для существующего профиля — из его файлов (и анкеты, если профиль создан мастером).
    Так можно править и профили, созданные вручную."""
    c = p.config
    saved = read_json(p.dir / ANSWERS_FILE, {})
    letter_cfg, analysis_cfg, search = c["письмо"], c["разбор"], c["поиск"]
    field = re.search(r"в сфере «(.+)»", analysis_cfg.get("для_кого", ""))
    where = search.get("где", [])
    city, city_area = next(((label, param.split("area=")[1].split("&")[0]) for label, param in where
                            if "REMOTE" not in param and "area=" in param), ("", ""))
    words = lambda spec: "\n".join(spec.get("слова", []) + spec.get("части", []))
    queries = [l.strip() for l in read_text(p.searches).splitlines() if l.strip() and not l.startswith("#")] \
        if p.searches.exists() else []
    resume_inside = p.resume.parent == p.dir.resolve()
    criteria = p.read_criteria() if p.criteria_file.exists() else ""
    # Пустые ответы анкеты (или нет анкеты) — берём из критериев, если их собирал мастер
    from_criteria = {k: v for k, v in answers_from_criteria(criteria).items()
                     if saved.get(k) in (None, "") or (k in ("office", "hybrid") and k not in saved)}
    return {
        "office": True, "hybrid": True, "salary": "", "important": "", "not_ok": "",   # по умолчанию
        **saved, **from_criteria,
        "profile_id": p.name,
        "name": c.get("имя", ""),
        "female": "рада" in letter_cfg.get("завершение", ""),
        "field": field.group(1) if field else saved.get("field", ""),
        "start": next((k for k, v in START.items() if v == letter_cfg.get("готовность")), "2 недели"),
        "part_time": "временные" in analysis_cfg.get("вступление", ""),
        "city": city,
        "city_area": city_area,
        "remote": any("REMOTE" in param for _, param in where),
        "titles": "\n".join(queries),
        "title_words": words(search.get("название_про_сферу", {})),
        "level_words": words(search.get("название_уровень", {})),
        "stop_words": "\n".join(search.get("стоп_слова", [])),
        "search_salary": str(search.get("зарплата_от") or ""),
        "search_salary_only": bool(search.get("только_с_зарплатой")),
        "search_salary_set": "зарплата_от" in search,
        "search_full_text": bool(search.get("весь_текст")),           # задавали ли фильтр (пусто — тоже выбор)
        "criteria": p.read_criteria() if p.criteria_file.exists() else "",
        "letter": read_text(p.letter_example).strip() if p.letter_example.exists() else "",
        "resume": p.read_resume() if p.resume.exists() else "",
        "facts": "".join(f"- {f}\n" for f in p.read_facts()),        # списком: видно, где кончается факт
        "resume_editable": resume_inside,
        "resume_file": str(p.resume),
        "model_pick": "none" if p.no_model else "cloud" if p.use_cloud else "local",   # шаг «Модель»
        "cloud": p.use_cloud,
        "no_model": p.no_model,
        "hide_firms": mask.hide_companies(p),
    }


def update_profile(p, answers, log=None):
    """Сохраняет правки из мастера. Меняется только то, что человек поменял: например, настроенные
    вручную критерии или фильтр по названию не пересобираются, если их не трогали. Возвращает список изменений."""
    log = log or log_print
    old = answers_from_profile(p)
    a = {**old, **answers}
    changed = lambda *keys: any(str(a.get(k) or "").strip() != str(old.get(k) or "").strip() for k in keys)
    done = _update_config(p.config, a, changed)
    p.save_config()
    done += _update_files(p, a, old, changed)
    if changed("model_pick") and a.get("model_pick") in ("local", "cloud", "none"):   # шаг «Модель» в мастере
        from . import cloud
        if a["model_pick"] == "cloud" and not cloud.load(p.dir.parent).get("auth_key"):
            raise AssistantError("Сначала подключите GigaChat: вставьте ключ и отметьте согласие на шаге «Модель».")
        p.set_model(a["model_pick"] == "cloud", off=a["model_pick"] == "none")
        done.append("модель")
    if changed("hide_firms"):
        mask.set_hide_companies(p, a.get("hide_firms"))
        done.append("скрытие прошлых работодателей")

    keep = {k: a.get(k) for k in ("office", "hybrid", "salary", "important", "not_ok", "field")}
    write_json(p.dir / ANSWERS_FILE, keep)
    name = p.name
    if changed("profile_id"):
        name = rename_profile(p, a["profile_id"])
        done.append("имя профиля")
    log(f"Профиль {name}: изменено — {', '.join(done) or 'ничего'}")
    return {"changed": done, "profile": name}




def _update_config(c, a, changed):
    """Правки мастера, которые живут в настройках профиля (config): имя, письмо, сфера, поиск. Возвращает, что изменено."""
    done = []
    if changed("name"):
        if c["письмо"].get("подпись") == c.get("имя"):
            c["письмо"]["подпись"] = a["name"].strip()
        c["имя"] = a["name"].strip()
        done.append("имя")
    if changed("female") and c["письмо"].get("завершение") in ("Буду рад обсудить детали.", "Буду рада обсудить детали."):
        c["письмо"]["завершение"] = "Буду рада обсудить детали." if a.get("female") else "Буду рад обсудить детали."
        done.append("подпись письма")
    if changed("field"):
        fresh = build_config({"name": "", **a})
        for key in ("для_кого", "общий_навык"):
            c["разбор"][key] = fresh["разбор"][key]
        done.append("сфера")
    if changed("start"):
        c["письмо"]["готовность"] = START.get(a.get("start"), START["2 недели"])
        done.append("когда можете выйти")
    if changed("part_time"):
        c["разбор"]["вступление"] = build_config({"name": "", **a})["разбор"]["вступление"]
        done.append("занятость")
    if changed("city", "remote"):
        c["поиск"]["где"] = build_config({"name": "", **a})["поиск"]["где"]
        done.append("где искать")
    if changed("title_words"):
        c["поиск"]["название_про_сферу"] = split_words(lines(a.get("title_words")))
        done.append("слова профессии")
    if changed("level_words"):
        c["поиск"]["название_уровень"] = split_words(lines(a.get("level_words")))
        done.append("слова уровня")
    if changed("stop_words"):
        c["поиск"]["стоп_слова"] = lines(a.get("stop_words"))
        done.append("стоп-слова")
    if changed("search_salary", "search_salary_only", "search_salary_set"):   # set — открыли шаг «Отбор при поиске»: пустое поле тоже выбор
        c["поиск"]["зарплата_от"] = int(re.sub(r"\D", "", str(a.get("search_salary") or "")) or 0) or None
        c["поиск"]["только_с_зарплатой"] = bool(a.get("search_salary_only"))
        done.append("зарплата в поиске")
    if changed("search_full_text"):
        c["поиск"]["весь_текст"] = bool(a.get("search_full_text"))
        done.append("где искать слова запроса")
    return done


def _update_files(p, a, old, changed):
    """Правки мастера в файлах профиля: запросы, критерии, образец письма, резюме, «о себе». Возвращает, что изменено."""
    c = p.config
    done = []
    if changed("titles"):
        head = [l for l in read_text(p.searches).splitlines() if l.startswith("#")] if p.searches.exists() else []
        write_text(p.searches, "\n".join(head + [""] + lines(a.get("titles"))).lstrip("\n") + "\n")
        done.append("поисковые запросы")
    if changed("criteria") and (a.get("criteria") or "").strip():
        from . import criteria_history
        criteria_history.record(p, old.get("criteria"), "до правки в профиле")       # прежний текст — в историю
        write_text(p.criteria_file, a["criteria"].strip() + "\n")
        # Новый текст — отдельной версией: правленный вручную или собранный из опросника
        # (если его взяли из прежних версий, такой текст уже есть — повтора не будет)
        origin = a.get("criteria_origin") or "manual"
        criteria_history.record(p, a["criteria"], {"questionnaire": "собраны из опросника",
                                                   "history": "взяты из прежних версий"}.get(origin, "изменены вручную"),
                                kind=origin if origin in ("manual", "questionnaire") else None)
        done.append("критерии")
    if changed("letter") and (a.get("letter") or "").strip():
        from . import criteria_history
        criteria_history.record(p, old.get("letter"), "до правки в профиле", which="letter")
        write_text(p.letter_example, a["letter"].strip() + "\n")
        origin = a.get("letter_origin") or "manual"
        criteria_history.record(p, a["letter"], "взят из прежних версий" if origin == "history" else "изменён вручную",
                                kind="manual" if origin != "history" else None, which="letter")
        done.append("образец письма")
    if changed("resume") and old["resume_editable"] and (a.get("resume") or "").strip():
        write_text(p.resume, a["resume"].strip() + "\n")
        done.append("резюме")
    elif a.get("resume_to_profile") and not old["resume_editable"] and (a.get("resume") or "").strip():
        # резюме было во внешнем файле — новое кладём в папку профиля, внешний файл не трогаем
        target = p.dir / "резюме.md"
        if target.exists():
            shutil.copy(target, target.with_name(f"резюме (до {date.today().strftime('%d.%m.%Y')}).md"))
        write_text(target, a["resume"].strip() + "\n")
        c["резюме"] = "резюме.md"
        p.save_config()
        done.append("резюме (теперь в папке профиля)")
    if changed("facts"):
        p.write_facts(a.get("facts"))
        done.append("дополнительно о себе")
    return done


def rename_profile(p, new):
    """Переименовывает папку профиля; поправляет путь для Obsidian, профиль по умолчанию и сводку."""
    from .profile import Profile
    from .summary import write_summary
    new = (new or "").strip()
    if not re.fullmatch(r"[\w-]{1,40}", new):
        raise AssistantError("Имя профиля — буквы, цифры, «-» или «_», без пробелов (например, maria).")
    root = p.dir.parent
    if (root / new).exists():
        raise AssistantError(f"Профиль «{new}» уже есть.")
    old = p.name
    p.dir.rename(root / new)
    config_file = root / new / CONFIG_FILE
    config = read_json(config_file)
    vault = config.get("путь_в_obsidian", "")
    if vault == old or vault.endswith("/" + old):
        config["путь_в_obsidian"] = vault[: len(vault) - len(old)] + new
        write_json(config_file, config)
    default = root / settings.DEFAULT_PROFILE_FILE
    if default.exists() and read_text(default).strip() == old:
        write_text(default, new + "\n")
    renamed = Profile(new, root)
    if renamed.summary.exists():                      # ссылки Meta Bind в сводке — с путём профиля
        write_summary(renamed, log=lambda *_: None)
    return new


def set_search_settings(p, days, limit):
    """Период поиска (1–30 дней) и сколько новых вакансий скачивать за поиск (пусто — все)."""
    days = int(days)
    if not 1 <= days <= 30:
        raise AssistantError("Период поиска — от 1 до 30 дней.")
    limit = None if limit in (None, "") else int(limit)
    if limit is not None and limit < 1:
        raise AssistantError("Сколько вакансий за поиск — число больше нуля или пусто (все).")
    p.config["поиск"]["дней"] = days
    p.config["поиск"]["максимум_новых"] = limit
    p.save_config()


def set_two_stage(p, on):
    """Как оценивать вакансии: в две ступени (быстрая оценка → полный разбор) или сразу полным разбором."""
    p.config["разбор"]["две_ступени"] = bool(on)
    p.save_config()


def set_columns(p, order, hidden):
    """Колонки таблицы в окне: порядок и скрытые. Пустые списки — как по умолчанию."""
    from .profile import clean_columns
    p.config["колонки"] = {"порядок": clean_columns(order), "скрыты": clean_columns(hidden)}
    if not any(p.config["колонки"].values()):
        p.config.pop("колонки")
    p.save_config()
    p.columns = {"order": clean_columns(order), "hidden": clean_columns(hidden)}


def set_saved_filters(p, items):
    """Сохранённые фильтры вкладки «Фильтр» — список целиком."""
    from .profile import clean_saved_filters
    p.saved_filters = clean_saved_filters(items)
    if p.saved_filters:
        p.config["фильтры"] = p.saved_filters
    else:
        p.config.pop("фильтры", None)
    p.save_config()


def set_hh_auto(p, on, risk=False):
    """Поиск на hh.ru программой: включить (с согласием на риск) или выключить — в настройках или в разовом
    вопросе для профилей прежних версий."""
    p.config["hh_авто"] = hh_auto(on, risk)
    p.config.pop("согласие_hh", None)                 # прежнее «понимаю правила» — больше не нужно
    p.save_config()
    p.hh_state, p.hh_auto = ("on", True) if on else ("off", False)


def set_llm_pages(p, on):
    """Согласие на разбор страниц вакансий с других сайтов моделью — можно дать и отозвать в настройках."""
    p.config["разбор"]["модель_для_страниц"] = bool(on)
    p.save_config()


