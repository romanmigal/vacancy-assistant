"""Общее для тестов: временная копия профиля-примера и поддельная модель."""
import hashlib
import re
import shutil
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(PROJECT))
# Файл «какая папка с данными» — свой у тестов: выбор папки в программе на этом компьютере их не касается
import os  # noqa: E402
os.environ["VACANCY_ASSISTANT_CONFIG"] = tempfile.mkdtemp(prefix="va-config-")

from vacancy_assistant import support  # noqa: E402
from vacancy_assistant.profile import Profile  # noqa: E402

# Журнал ошибок тестов — во временной папке, не в журнале программы на этом компьютере
TEST_LOG = Path(tempfile.mkdtemp(prefix="va-log-")) / support.LOG_NAME
support.log_path = lambda: TEST_LOG
from vacancy_assistant.textio import write_text  # noqa: E402

VACANCY_HTML = """<html><body>
<h1 data-qa="vacancy-title"><span>ИТ-директор</span></h1>
<a data-qa="vacancy-company-name"><span>ООО&nbsp;Пример</span></a>
<span data-qa="vacancy-salary">от 500 000 ₽ за месяц на руки</span>
<p data-qa="vacancy-experience">более 6 лет</p>
<p data-qa="vacancy-view-location">Москва</p>
<div data-qa="vacancy-description"><p><strong>Задачи:</strong></p><ul><li>руководить ИТ</li><li>строить <b>команду</b></li></ul><div>Вложенный блок</div></div>
<div>после описания</div>
</body></html>"""



def vacancy_page(url):
    """VACANCY_HTML для вакансии по адресу: адрес офиса свой у каждого номера — иначе одинаковые страницы
    под разными номерами — это дубль (работодатель опубликовал вакансию несколько раз), и вторую не сохраняем."""
    vid = re.search(r"/vacancy/(\d+)", url)
    return VACANCY_HTML.replace(">Москва<", f">Москва, офис {vid.group(1)}<") if vid else VACANCY_HTML


SEARCH_HTML = """<div>
<a class="x" data-qa="serp-item__title" href="https://hh.ru/vacancy/111111?query=CTO&amp;from=a"><span>Технический директор (CTO)</span></a>
<a data-qa="serp-item__title" href="https://hh.ru/vacancy/222222"><span>Начальник отдела ИТ</span></a>
<a data-qa="serp-item__title" href="/vacancy/333333?x=1"><span>Директор по информационным технологиям &amp; цифре</span></a>
</div>"""


def answer_for(prompt, score=8, decision="да"):
    tag = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:8]
    return (f"Критерии:\nК1: ✅ — Москва\nК2: ❓ — зарплата не указана\n\n"
            f"Могу: 7/10 — опыт есть\nХочу: {score}/10 — интересно\nОценка: {score}/10\n\n"
            f"Сильные стороны: опыт {tag}\nПробелы: нет\n\nОткликаться: {decision}")


def fake_model(prompt, model=None, options=None):
    """Поддельная модель: письмо — для промпта письма, разбор — для остального. Оценка зависит от
    вакансии: «отдела» в тексте — 3 и «нет», иначе 8 и «да»."""
    if "личное сообщение знакомому" in prompt:
        return "Иван, привет!\n\nУвидел вакансию в твоей компании. Подскажешь, стоит ли откликаться?\n\nИван Петров"
    if "по методу STAR" in prompt:
        return ("## 1. Запуск ИТ с нуля\n**Под требование:** опыт в банке\n**Ситуация:** новый банк\n"
                "**Действия:** [уточните: главная сложность]\n\n## Где будут спрашивать о пробелах\n- нет BPM"
                + ("\n\n## Мои вопросы работодателю\n1. Кому подчиняется роль? — пойму полномочия\n"
                   "2. Почему открыта позиция? — пойму, что не получилось" if "Мои вопросы работодателю" in prompt else ""))
    if "подогнать резюме под конкретную вакансию" in prompt:
        return ("## Включить в резюме под вакансию\n1. Перевод ИТ в облако (Пример Ритейл) — цифровизация (резюме)\n\n"
                "## Можно не включать\n- Поддержка 1С — вакансии не нужна\n\n## Обо мне\nИТ-директор в ритейле.\n\n"
                "## Ключевые навыки\n**Выделить — уже есть в резюме:** облако, команда\n"
                "**Слова из вакансии, которых нет в резюме** (добавляйте, только если это правда):\n- ERP — [уточните: был ли у вас такой опыт и где]")
    if "Подготовь только вопросы работодателю" in prompt:
        return ("## Мои вопросы работодателю\n1. Какой бюджет ИТ на год? — пойму масштаб\n"
                "2. Чего ждёте через 3 месяца? — пойму ожидания\n3. Кто в команде? — пойму, с кем работать")
    if "сопроводительное письмо" in prompt:
        return "Здравствуйте!\n\nОткликаюсь на позицию.\n\nИван Петров"
    if "Начальник отдела" in prompt:
        return answer_for(prompt, 3, "нет")
    return answer_for(prompt)


class TempProfile:
    """Копия тестового профиля (tests/fixtures/профили/example) во временной папке: тесты не трогают настоящие данные."""

    def __enter__(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="vacancy-test-"))
        self.profiles = self.tmp / "профили"
        self.profiles.mkdir()
        shutil.copytree(FIXTURES / "профили" / "example", self.profiles / "example")
        self.profile = Profile("example", self.profiles)
        return self

    def add_vacancy(self, number, title, company="ООО Пример", salary="не указана", saved="16.10.2026"):
        path = self.profile.vacancies / f"{number:02d} {title} — {company}.md"
        write_text(path, f"# {title}\n\n**Компания:** {company}  \n**Зарплата:** {salary}  \n"
                         f"**Ссылка:** https://hh.ru/vacancy/{100000 + number}  \n**Сохранено:** {saved}\n\n---\n\n"
                         f"Описание вакансии «{title}».\n")
        return path

    def __exit__(self, *exc):
        shutil.rmtree(self.tmp, ignore_errors=True)
