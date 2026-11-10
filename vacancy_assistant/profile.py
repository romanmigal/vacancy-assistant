"""Профиль человека: папка профили/<имя>/ с настройками, резюме, критериями и данными."""
import hashlib
import json
import re
from datetime import date

from . import settings
from .errors import AssistantError
from .textio import read_json, read_text, write_json, write_text

ANSWERS_FILE = "анкета.json"      # ответы опросника «Что ищете» (пишет setup)

# (?<!\w)…(?!\w) — целое слово: иначе «ИТ» находится внутри «развИТия»
W = lambda words: rf"(?<!\w)(?:{words})(?!\w)"

# Отбор по названию. Аббревиатуры должностей бывают набраны кириллицей целиком или частью: «СТО», «IТ».
# Приводим к латинице только их — и только если получилась известная аббревиатура
LOOKALIKE = str.maketrans("АВЕКМНОРСТХаеорсух", "ABEKMHOPCTXaeopcyx")
ROLE_ABBR = {"CTO", "CIO", "CDO", "CEO", "COO", "IT"}
ABBR = re.compile(r"(?<!\w)[A-ZА-ЯЁ]{2,3}(?!\w)")
# «СТО» по-русски — ещё и станция техобслуживания: рядом с этими словами — не CTO
CAR_SERVICE = re.compile(r"мастер|при[её]мщик|автосервис|автомоб|сервисн\w* центр|техобслуж|"
                         r"(?:региональн|сет)\w*\s+СТО|СТО\s+(?:премиум|сети)", re.I)
# «Технический директор» без слов про ИТ в профиле сферы ИТ — пропускаем на оценку моделью,
# если в названии нет признаков другой отрасли. Свой список — «поиск» → «другие_отрасли» в профиль.json
OTHER_INDUSTRIES = ["производ", "завод", "фабрик", "цех", "ЖКХ", "ОВиК", "климат", "вентиляц", "строит", "монтаж",
                    "агро", "сельскохоз", "склад", "логистич", "пищев", "фарм", "GMP", "медицин", "клиник",
                    "ритейл", "магазин", "ресторан", "гостиниц", "отел", "ателье", "швейн", "типограф",
                    "рекламн", "энерг", "нефт", "газ", "горн", "карьер", "ПГС", "транспорт", "автопарк",
                    "мастер", "при[её]мщик", "СТО\b", "технолог"]
FACT_MARK = re.compile(r"^\s*(?:[-*•]|\d+[.)])(?:\s+|$)")


def parse_facts(text):
    """Факты «Дополнительно о себе». Если строки начинаются с «-» (или «*», «•», «1.»), факт — от маркера до
    следующего: строка без маркера — продолжение предыдущего факта. Без маркеров — факт на строку."""
    lines = [l for l in (text or "").splitlines() if l.strip() and not l.lstrip().startswith("#")]
    marked = any(FACT_MARK.match(l) for l in lines)
    facts = []
    for line in lines:
        if not marked or FACT_MARK.match(line) or not facts:
            facts.append(FACT_MARK.sub("", line).strip())
        else:
            facts[-1] = f"{facts[-1]} {line.strip()}".strip()
    return [f for f in facts if f]


TECH_DIRECTOR = re.compile(r"техническ\w*\s+директор|директор\s+по\s+техническ", re.I)


def _norm_hash(text):
    """Короткий отпечаток текста без учёта пробелов и переносов."""
    return hashlib.sha256(" ".join(text.split()).encode("utf-8")).hexdigest()[:10]


def plain_title(title):
    """Название для отбора: «Технический директор (СТО)» → «… (CTO)», «IТ-директор» → «IT-директор».
    Название вакансии в файле не меняется — это только для сравнения."""
    car = bool(CAR_SERVICE.search(title))

    def fix(m):
        latin = m.group(0).translate(LOOKALIKE)
        return latin if latin in ROLE_ABBR and not (car and latin == "CTO") else m.group(0)
    return ABBR.sub(fix, title)


def words_regex(spec):
    """{"слова": [...целые слова], "части": [...части слов]} → одно регулярное выражение."""
    alts = []
    if spec.get("части"):
        alts.append("|".join(spec["части"]))
    if spec.get("слова"):
        alts.append(W("|".join(spec["слова"])))
    return "|".join(alts) or r"(?!)"


def profile_names(profiles_dir=None):
    """Профили — папки с профиль.json (пока их нет — пустой список: окно откроет мастер)."""
    root = profiles_dir or settings.profiles_dir()
    return sorted(d.name for d in root.iterdir() if (d / CONFIG_FILE).exists()) if root.is_dir() else []


def default_profile_name(profiles_dir=None):
    """Имя профиля по умолчанию — из профили/по_умолчанию.txt, иначе первый по алфавиту; профилей нет — None."""
    root = profiles_dir or settings.profiles_dir()
    names = profile_names(root)
    f = root / settings.DEFAULT_PROFILE_FILE
    name = read_text(f).strip() if f.exists() else ""
    return name if name in names else (names[0] if names else None)


CONFIG_FILE = "профиль.json"


MAX_CUSTOM_STATUSES = 5
STATUS_COLORS = ["blue", "violet", "orange", "teal", "pink"]   # значки своих статусов


def clean_columns(keys):
    """Ключи колонок таблицы из профиля или окна: только похожие на ключ строки, без повторов."""
    out = []
    for k in keys if isinstance(keys, list) else []:
        if isinstance(k, str) and re.fullmatch(r"[a-z_]{1,20}", k) and k not in out:
            out.append(k)
    return out[:40]


MAX_SAVED_FILTERS = 20


def clean_saved_filters(items):
    """Сохранённые фильтры вкладки «Фильтр»: [{"name", "f", "closed"}]. Имя — до 40 знаков, без повторов;
    f — фильтры колонок окна {ключ колонки: условия}; слишком большой фильтр не берём."""
    out, names = [], set()
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict) or not isinstance(it.get("f"), dict):
            continue
        name = re.sub(r"\s+", " ", str(it.get("name") or "")).strip()[:40]
        f = {k: v for k, v in it["f"].items() if isinstance(k, str) and re.fullmatch(r"[a-z_]{1,20}", k) and isinstance(v, dict)}
        if not name or name.lower() in names or len(json.dumps(f, ensure_ascii=False)) > 20000:
            continue
        names.add(name.lower())
        out.append({"name": name, "f": f, "closed": bool(it.get("closed"))})
    return out[:MAX_SAVED_FILTERS]


def free_color(colors):
    """Цвет значка для нового своего статуса: первый из STATUS_COLORS, которого ещё нет; все заняты — по кругу."""
    used = list(colors)
    return next((c for c in STATUS_COLORS if c not in used), STATUS_COLORS[len(used) % len(STATUS_COLORS)])


def clean_statuses(items):
    """Свои статусы из профиль.json: [{"ключ": "c1", "название": "Отложено", "цвет": "blue"}] →
    ([("c1", "Отложено")], {"c1": "blue"}), не больше пяти. Нет цвета (профиль прежней версии) — свободный."""
    out, colors = [], {}
    for x in items if isinstance(items, list) else []:
        key, name = (x.get("ключ"), x.get("название")) if isinstance(x, dict) else (None, None)
        if (isinstance(key, str) and re.fullmatch(r"c\d", key) and isinstance(name, str) and name.strip()
                and key not in dict(out) and len(out) < MAX_CUSTOM_STATUSES):
            out.append((key, name.strip()))
            colors[key] = x.get("цвет") if x.get("цвет") in STATUS_COLORS else free_color(colors.values())
    return out, colors


# Сообщение референсеру: цель — (название, чего хотим, просьба в конце) и канал — (название, правила формы)
REFERRER_GOALS = {
    "pass": ("передать резюме", "передал моё резюме нанимающему руководителю или HR и, если сочтёт возможным, порекомендовал меня",
             "передать моё резюме нанимающему руководителю или HR — пришлю его, куда удобно."),
    "learn": ("узнать о роли", "рассказал, что это за роль и команда, и подсказал, стоит ли мне откликаться",
              "15 минут созвона или пару слов в ответ: что за команда, кого на самом деле ищут, стоит ли мне откликаться."),
}
REFERRER_CHANNELS = {
    "telegram": ("Telegram", "Форма: сообщение в Telegram, 400–700 знаков, 3–4 коротких абзаца, без темы."),
    "linkedin": ("LinkedIn", "Форма: сообщение в LinkedIn, до 700 знаков, без темы."),
    "invite": ("запрос в контакты LinkedIn", "Форма: приписка к запросу в контакты LinkedIn — не больше 300 знаков, 2–3 предложения."),
    "setka": ("Сетка (соцсеть hh.ru)", "Форма: сообщение в Сетке, до 700 знаков, без темы."),
    "email": ("электронная почта", "Форма: письмо — первая строка «Тема: …», дальше текст до 1200 знаков."),
}


FACTS_FILE = "о себе.md"
# Шаблоны разбора требуют подтверждения «в резюме» — без прямого указания модель факты отсюда не засчитывала
FACTS_HEAD = ("Дополнительно о себе — этого нет в резюме выше, но это тоже правда о моём опыте. Считай эти факты частью "
              "резюме: требование вакансии, которое подтверждается фактом отсюда, считай подтверждённым (✅) — так же, "
              "как фактом из резюме, и ссылайся на этот факт. Учитывай их в «Могу», в сильных сторонах, в пробелах "
              "и в общей оценке. Правило «опирайся только на факты из резюме» относится и к этим фактам.")

class Profile:
    """Пути к данным и личные настройки одного человека."""

    def save_config(self):
        """Записывает изменённые настройки (self.config) в профиль.json."""
        write_json(self.dir / CONFIG_FILE, self.config)

    def __init__(self, name, profiles_dir=None):
        self.name = name
        self.dir = (profiles_dir or settings.profiles_dir()) / name
        config_file = self.dir / CONFIG_FILE
        if not config_file.exists():
            raise AssistantError(f"Нет профиля «{name}». Создайте профиль в окне программы: python3 razbor.py app")
        self.config = read_json(config_file)
        c = self.config
        self.vault_prefix = c.get("путь_в_obsidian", "").strip("/")   # путь от корня хранилища Obsidian
        self.resume = (self.dir / c["резюме"]).resolve()
        self._paths()
        self.letter_min_score = c["письмо"]["минимальная_оценка"]
        # Две ступени: быстрая оценка всех, полный разбор — только «да» и «возможно». False — сразу полный разбор
        self.two_stage_setting = c["разбор"].get("две_ступени", True)
        # Согласие человека: модель разбирает страницы вакансий с других сайтов (вырезает вакансию, ищет поля)
        self.llm_pages = bool(c["разбор"].get("модель_для_страниц", False)) and not self.no_model
        # Поиск и скачивание с hh.ru программой — только с согласия: соглашение hh запрещает скрипты.
        # "on" — включено с согласием, "off" — выключено, "ask" — профиль прежней версии: пока человек
        # не выбрал, на hh.ru не ходим
        hh = c.get("hh_авто")
        self.hh_state = ("on" if hh.get("включено") and hh.get("согласие") else "off") if isinstance(hh, dict) else "ask"
        self.hh_auto = self.hh_state == "on"
        self._window(c)
        self._search(c["поиск"])

    def _paths(self):
        """Папки и файлы профиля."""
        self.facts_file = self.dir / FACTS_FILE         # «Дополнительно о себе» — факты вне резюме
        self.vacancies = self.dir / "vacancies"        # сюда кладём вакансии (.md)
        self.results = self.dir / "разборы"            # сюда пишутся разборы
        self.letters = self.dir / "письма"
        self.referrer_letters = self.letters / "референсеру"   # сообщения референсерам (свои версии — в «история»)
        self.interview = self.dir / "интервью"         # истории STAR к собеседованиям
        self.resume_fits = self.dir / "резюме под вакансию"   # как подогнать резюме (прежние версии — в «история»)
        self.summary = self.dir / "Сводка.md"          # итоговая таблица
        self.status_file = self.dir / "vacancy-status.md"
        self.searches = self.dir / "поиски.txt"        # запросы для автопоиска
        self.seen = self.dir / "просмотрено.txt"       # память о просмотренных вакансиях
        self.ratings = self.dir / "мои-оценки.md"
        self.criteria_file = self.dir / "критерии.txt"
        self.letter_example = self.dir / "образец письма.txt"

    def _window(self, c):
        """Настройки окна: колонки, сохранённые фильтры, свои статусы."""
        # Колонки таблицы в окне: порядок и скрытые (ключи колонок окна; пусто — как по умолчанию)
        cols = c.get("колонки") if isinstance(c.get("колонки"), dict) else {}
        self.columns = {"order": clean_columns(cols.get("порядок")), "hidden": clean_columns(cols.get("скрыты"))}
        # Сохранённые фильтры вкладки «Фильтр» (например, «Плати по всему миру после 20.09»)
        self.saved_filters = clean_saved_filters(c.get("фильтры"))
        # Свои статусы (до пяти) — вкладки перед «Архивом»: [("c1", "Отложено"), …]; ключ не меняется при переименовании.
        # status_colors — цвет значка каждого: {"c1": "blue"}
        self.custom_statuses, self.status_colors = clean_statuses(c.get("статусы"))

    def _search(self, search):
        """Настройки поиска: где, сколько, фильтр по зарплате и отсев по названию до модели."""
        self.search_where = [tuple(w) for w in search["где"]]
        self.search_days = search["дней"]
        # Сколько новых подходящих вакансий скачивать за поиск (остальные — в следующий раз); None — все
        self.search_limit = search.get("максимум_новых", 50)
        # Фильтр hh.ru по зарплате: «от» в рублях (None — без фильтра) и «только с указанной зарплатой».
        # Не задавали на шаге «Отбор при поиске» — берём «Зарплата от» из опросника (анкета.json);
        # сохранили пустым — без фильтра
        if "зарплата_от" in search:
            self.search_salary = search.get("зарплата_от") or None
        else:
            asked = read_json(self.dir / ANSWERS_FILE, {}) if (self.dir / ANSWERS_FILE).exists() else {}
            self.search_salary = int(re.sub(r"\D", "", str(asked.get("salary") or "")) or 0) or None
        self.search_salary_only = bool(search.get("только_с_зарплатой"))
        # Слова запроса на hh.ru — по всему тексту вакансии, а не только в названии (по умолчанию — в названии)
        self.search_full_text = bool(search.get("весь_текст"))
        # Отсев по названию до модели — бесплатно: нужно и «про сферу», и «уровень», и ни одного стоп-слова
        # пустой список слов — проверка не нужна (так создаёт профиль мастер: уровень оценивает модель)
        self.title_it = words_regex(search["название_про_сферу"]) if any(search["название_про_сферу"].values()) else ""
        self.title_level = words_regex(search["название_уровень"]) if any(search["название_уровень"].values()) else ""
        self.title_stop = "|".join(search["стоп_слова"]) or r"(?!)"
        others = search.get("другие_отрасли")
        self.other_industries = "|".join(others if isinstance(others, list) else OTHER_INDUSTRIES) or r"(?!)"

    @property
    def display_name(self):
        return self.config["имя"]

    def vault_path(self, *parts):
        """Путь от корня хранилища Obsidian — для ссылок Meta Bind (по имени нельзя: имена повторяются)."""
        return "/".join(x for x in (self.vault_prefix, *parts) if x)

    def read_resume(self):
        return read_text(self.resume)

    def read_facts(self):
        """Факты из «о себе.md» — списком; заголовки Obsidian отбрасываются (parse_facts)."""
        return parse_facts(read_text(self.facts_file)) if self.facts_file.exists() else []

    def write_facts(self, text):
        write_text(self.facts_file, "".join(f"- {f}\n" for f in parse_facts(text)))

    def with_facts(self, resume):
        """Резюме и следом — факты «о себе» отдельным блоком; фактов нет — резюме как есть."""
        facts = self.read_facts()
        return resume.rstrip("\n") + "\n\n" + FACTS_HEAD + "\n" + "\n".join(f"- {f}" for f in facts) if facts else resume

    @property
    def use_cloud(self):
        """Выбран ли в профиле облачный GigaChat (с согласием этого человека). Профили прежних версий,
        где выбора ещё нет, наследуют общую настройку — она была одна на все профили."""
        choice = self.config.get("модель")
        if choice is not None:
            return bool(choice.get("облако"))
        from . import cloud
        legacy = cloud.load(self.dir.parent)
        return bool(legacy.get("enabled") and legacy.get("consent"))

    def set_model(self, use_cloud, off=False):
        """Выбор модели для профиля: GigaChat (с датой согласия), локальная или «Без модели» (off)."""
        self.config["модель"] = ({"облако": False, "без_модели": True} if off else
                                 {"облако": True, "согласие": date.today().isoformat()} if use_cloud else {"облако": False})
        self.save_config()

    @property
    def no_model(self):
        """Режим «Без модели»: программа — трекер откликов; всё, что зовёт модель, недоступно,
        вакансии сохраняются без разбора."""
        return bool((self.config.get("модель") or {}).get("без_модели"))

    @property
    def two_stage(self):
        """Оценивать ли в две ступени. Только для локальной модели: облачный GigaChat отвечает за секунды,
        поэтому с ним каждая вакансия всегда получает полный разбор."""
        from . import cloud
        return self.two_stage_setting and not cloud.active(self)

    def read_criteria(self):
        return read_text(self.criteria_file).rstrip("\n")

    def criteria_hash(self):
        """Отпечаток текущих критериев (без учёта пробелов) и фактов «о себе» — запоминается в оценке вакансии,
        чтобы потом видеть, что они с тех пор поменялись. Фактов нет — отпечаток как раньше, по одним критериям."""
        text = " ".join(self.read_criteria().split()) if self.criteria_file.exists() else ""
        facts = self.read_facts()
        if facts:
            text += "\nо себе: " + " | ".join(" ".join(f.split()) for f in facts)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]

    def input_hashes(self):
        """Отпечатки того, по чему модель оценивает, — по отдельности: критерии, резюме, «о себе».
        Для истории разборов: видно, что поменялось между разборами."""
        return {"criteria": _norm_hash(self.read_criteria() if self.criteria_file.exists() else ""),
                "resume": self.resume_hash(),
                "facts": _norm_hash(" | ".join(self.read_facts()))}

    def resume_hash(self):
        """Отпечаток резюме (без учёта пробелов) — запоминается в оценке: поменяли резюме — оценка устарела."""
        return _norm_hash(self.read_resume() if self.resume.exists() else "")

    def title_fits(self, title):
        title = plain_title(title)
        if not re.search(self.title_level, title, re.I) or re.search(self.title_stop, title, re.I):
            return False
        if re.search(self.title_it, title, re.I):
            return True
        # «Технический директор» без слов про ИТ: в профиле сферы ИТ — подходит, если не про другую отрасль
        return bool(self.it_field and TECH_DIRECTOR.search(title) and not re.search(self.other_industries, title, re.I))

    def title_reason(self, title):
        """Почему название не прошло отбор — для «Итогов недели»: стоп-слово, уровень или сфера; подходит — None."""
        if self.title_fits(title):
            return None
        plain = plain_title(title)
        stop = re.search(self.title_stop, plain, re.I)
        if stop:
            return f"стоп-слово «{stop.group(0).lower()}»"
        return "нет слова об уровне" if not re.search(self.title_level, plain, re.I) else "нет слова про сферу"

    @property
    def it_field(self):
        """Профиль сферы ИТ: слова «про сферу» находят IT, ИТ или CTO."""
        return bool(self.title_it) and any(re.search(self.title_it, w, re.I) for w in ("IT", "ИТ", "CTO"))

    def analysis_prompt(self, resume, vacancy, criteria=None):
        """Промпт разбора: общий шаблон + критерии и формулировки из профиля (criteria — для автонастройки)."""
        a = self.config["разбор"]
        if criteria is None:
            criteria = self.read_criteria()
        nums = re.findall(r"^К(\d+)\.", criteria, re.M)
        criteria_format = "Критерии:\n" + "\n".join(
            f"К{n}: ✅ / ❌ / ❓ — " + ("одна фраза с фактом из вакансии" if i == 0 else "...")
            for i, n in enumerate(nums))
        t = read_text(settings.ANALYSIS_TEMPLATE)
        for k, v in (("{audience}", a["для_кого"]), ("{intro}", a["вступление"]),
                     ("{general_skill}", a["общий_навык"]), ("{criteria_format}", criteria_format),
                     ("{criteria}", criteria)):
            t = t.replace(k, v)
        return t.replace("{resume}", self.with_facts(resume)).replace("{vac}", vacancy)

    def scoring_prompt(self, resume, vacancy, criteria=None):
        """Промпт короткого скоринга: те же критерии, ответ — отметки К, «Могу», «Хочу», оценка, решение."""
        a = self.config["разбор"]
        if criteria is None:
            criteria = self.read_criteria()
        marks = "\n".join(f"К{n}: ✅ / ❌ / ❓" for n in re.findall(r"^К(\d+)\.", criteria, re.M))
        t = read_text(settings.SCORING_TEMPLATE)
        for k, v in (("{audience}", a["для_кого"]), ("{intro}", a["вступление"]),
                     ("{criteria_marks}", marks), ("{criteria}", criteria)):
            t = t.replace(k, v)
        return t.replace("{resume}", self.with_facts(resume)).replace("{vac}", vacancy)

    def interview_prompt(self, resume, vacancy, analysis_text, template=None):
        """Промпт подготовки к собеседованию: истории STAR под требования вакансии, ответы о пробелах и вопросы
        работодателю. template — другой шаблон с теми же полями (только вопросы)."""
        t = read_text(template or settings.INTERVIEW_TEMPLATE).replace("{who}", self.config["письмо"]["кому_помогаем"])
        return t.replace("{resume}", resume).replace("{vac}", vacancy).replace("{analysis}", analysis_text)

    def referrer_prompt(self, resume, vacancy, strengths_text, title, to, about, channel, goal, extra=""):
        """Промпт сообщения референсеру: кому, что о нём известно, канал и цель — из окна «Письма»."""
        g = REFERRER_GOALS.get(goal, REFERRER_GOALS["pass"])
        c = REFERRER_CHANNELS.get(channel, REFERRER_CHANNELS["telegram"])
        t = read_text(settings.REFERRER_TEMPLATE)
        for k, v in (("{who}", self.config["письмо"]["кому_помогаем"]), ("{goal}", g[1]), ("{ask}", g[2]),
                     ("{to}", to), ("{about}", about or "ничего, кроме имени и должности"), ("{channel}", c[0]),
                     ("{channel_rules}", c[1]), ("{title}", title), ("{signature}", self.config["письмо"]["подпись"]),
                     ("{extra}", f"- Ещё учти: {extra.strip()}" if (extra or "").strip() else "")):
            t = t.replace(k, v)
        return t.replace("{resume}", resume).replace("{vac}", vacancy).replace("{strengths}", strengths_text)

    def resume_fit_prompt(self, resume, vacancy, strengths_text):
        """Промпт «Резюме под вакансию»: что включить (из резюме и «Дополнительно о себе»), что можно
        не включать, «Обо мне» языком вакансии, ключевые навыки. Фактов «о себе» нет — то же только по резюме."""
        facts = self.read_facts()
        t = read_text(settings.RESUME_FIT_TEMPLATE)
        for k, v in (("{who}", self.config["письмо"]["кому_помогаем"]),
                     ("{source_note}", "откуда: резюме или Дополнительно о себе — добавьте в резюме" if facts
                      else "откуда: место в резюме"),
                     ("{facts_also}", " и «Дополнительно о себе»" if facts else ""),
                     ("{facts_rule}", "\nФакт из «Дополнительно о себе» в резюме ещё нет — у такого пункта в скобках пиши дословно: "
                      "(Дополнительно о себе — добавьте в резюме)." if facts else ""),
                     ("{facts}", "\n=== ДОПОЛНИТЕЛЬНО О СЕБЕ (этого нет в резюме, но это правда о моём опыте) ===\n"
                      + "\n".join(f"- {f}" for f in facts) + "\n" if facts else "")):
            t = t.replace(k, v)
        return t.replace("{resume}", resume).replace("{vac}", vacancy).replace("{strengths}", strengths_text)

    def letter_prompt(self, resume, vacancy, strengths_text, example=None):
        """Промпт письма: общий шаблон + образец, подпись и фразы из профиля. example — свой образец
        для этого письма (поправили перед тем, как писать), иначе — образец профиля."""
        l = self.config["письмо"]
        example = (example or read_text(self.letter_example)).strip()
        t = read_text(settings.LETTER_TEMPLATE)
        for k, v in (("{who}", l["кому_помогаем"]), ("{example}", example), ("{availability}", l["готовность"]),
                     ("{closing}", l["завершение"]), ("{signature}", l["подпись"])):
            t = t.replace(k, v)
        return t.replace("{resume}", resume).replace("{vac}", vacancy).replace("{strengths}", strengths_text)
