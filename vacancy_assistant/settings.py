"""Общие настройки: где лежат данные и шаблоны, какая модель."""
import os
import sys
from pathlib import Path

from . import datadir

# Папка проекта (там razbor.py); в собранной программе — папка с её файлами (шаблоны, профиль-пример)
PROJECT_DIR = Path(getattr(sys, "_MEIPASS", None) or Path(__file__).resolve().parent.parent)


def data_root():
    """Корень данных: папка с профилями. Переменная VACANCY_ASSISTANT_HOME (её ставит установленная программа),
    иначе папка, выбранная в «Настройки → Папка с данными» (datadir), иначе папка проекта."""
    return Path(os.environ.get("VACANCY_ASSISTANT_HOME") or datadir.saved() or PROJECT_DIR)


def profiles_dir():
    return data_root() / "профили"


TEMPLATES = PROJECT_DIR / "шаблоны"                        # общие части промптов
ANALYSIS_TEMPLATE = TEMPLATES / "разбор v7.txt"            # полный разбор — для «да» и «возможно»
# Короткий скоринг: только критерии, «Могу», «Хочу», оценка и решение — в 4 раза быстрее полного разбора
# (опыт 22.10: 15 с против 63 с на вакансию, решения на эталоне те же). Его проходят все вакансии.
SCORING_TEMPLATE = TEMPLATES / "скоринг v1.txt"
LETTER_TEMPLATE = TEMPLATES / "письмо v6.txt"            # по образцу, своим отправленным письмам и требованиям вакансии; рамку ставит letter_frame
INTERVIEW_TEMPLATE = TEMPLATES / "интервью v2.txt"         # истории STAR к собеседованию и вопросы работодателю
QUESTIONS_TEMPLATE = TEMPLATES / "вопросы работодателю v1.txt"   # только вопросы — к подготовке без них
STORIES_TEMPLATE = TEMPLATES / "интервью v1.txt"           # только истории — когда вопросы уже есть и остаются
RESUME_FIT_TEMPLATE = TEMPLATES / "резюме под вакансию v2.txt"   # что включить и что можно не включать, «Обо мне», навыки
REFERRER_TEMPLATE = TEMPLATES / "референсеру v1.txt"       # личное сообщение знакомому в компании вакансии
MARKET_TEMPLATE = TEMPLATES / "резюме против рынка v2.txt"   # что дописать и что нарастить: отклики и «модель — нет, вы — да»
EXAMPLES = PROJECT_DIR / "примеры"                         # образцы резюме и критериев для мастера (вымышленный человек)
DEFAULT_PROFILE_FILE = "по_умолчанию.txt"                  # локально: имя своего профиля

MODEL = "gemma4:12b"
OLLAMA = "http://127.0.0.1:11434/api/generate"
OPTIONS = {"temperature": 0.3, "num_predict": 1500, "num_ctx": 12288}
SCORING_OPTIONS = {**OPTIONS, "num_predict": 200}

# Сопроводительные письма. Сравнение на промпте v2 (20.10): GigaChat в 3 раза быстрее,
# но в 3 письмах из 6 ошиблась с форматом работы и копировала образец; Gemma — без ошибок
LETTER_MODEL = MODEL
LETTER_OPTIONS = {"temperature": 0.5, "num_predict": 800, "num_ctx": 12288}
INTERVIEW_OPTIONS = {"temperature": 0.4, "num_predict": 3000, "num_ctx": 16384}
QUESTIONS_OPTIONS = {**INTERVIEW_OPTIONS, "num_predict": 800}
RESUME_FIT_OPTIONS = {"temperature": 0.3, "num_predict": 1500, "num_ctx": 16384}
MARKET_OPTIONS = {"temperature": 0.3, "num_predict": 1500, "num_ctx": 16384}

RELEASES_PAGE = "https://github.com/romanmigal/job-search-assistant-releases/releases"   # публичный репозиторий: только релизы
UPDATES_URL = RELEASES_PAGE + "/latest/download/latest.json"                             # проверка обновлений
CONTACT_EMAIL = "job_search_assistant@inbox.ru"           # «О программе» и README: ошибки, вопросы, идеи
CHAT_URL = "https://t.me/vacancy_assistant_chat"         # чат пользователей в Telegram — «О программе» и README; пусто — без ссылки
DONATE_URL = "https://pay.cloudtips.ru/p/41e4a0ff"         # «Поддержать проект» в «О программе» и README; пусто — без ссылки
SOURCE_URL = "https://github.com/romanmigal/vacancy-assistant"   # исходный код (GPL-3.0) — ссылка в «О программе»; пусто — без ссылки
# Установка и обновление на Mac командой в Терминале: без карантина — без предупреждения о неподписанной программе
MAC_INSTALL = "curl -fsSL https://raw.githubusercontent.com/romanmigal/vacancy-assistant/main/packaging/install_mac.sh | bash"

# hh.ru отдаёт страницу только «браузеру», поэтому представляемся Chrome
USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126 Safari/537.36")
