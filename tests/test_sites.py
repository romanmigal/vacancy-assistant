"""Вакансии с любых сайтов: разметка JobPosting, обычная страница, страница без текста, вставленный текст."""
import json
import re
import unittest

from helpers import VACANCY_HTML, TempProfile

from vacancy_assistant import sites
from vacancy_assistant.errors import AssistantError
from vacancy_assistant.files import read_vacancy
from vacancy_assistant.textio import read_text, write_text

DESCRIPTION = "<p>Чем заниматься:</p><ul><li>руководить ИТ-направлением</li><li>строить команду разработки</li></ul>" * 6

JOBPOSTING_PAGE = f"""<html><head><title>CIO — Карьера в Ромашке</title>
<script type="application/ld+json">{json.dumps({"@context": "https://schema.org", "@graph": [
    {"@type": "Organization", "name": "Ромашка"},
    {"@type": "JobPosting", "title": "Директор по ИТ (CIO)", "description": DESCRIPTION,
     "hiringOrganization": {"@type": "Organization", "name": "ООО Ромашка"},
     "jobLocation": {"@type": "Place", "address": {"addressLocality": "Москва"}},
     "baseSalary": {"currency": "RUB", "value": {"minValue": 500000, "maxValue": 700000, "unitText": "MONTH"}}}]},
    ensure_ascii=False)}</script></head><body><nav>Меню сайта</nav><h1>Директор по ИТ (CIO)</h1></body></html>"""

PLAIN_PAGE = f"""<html><head><title>Технический директор — Работа в Лютике</title>
<meta property="og:title" content="Технический директор — Работа в Лютике"></head>
<body><header>Шапка и меню</header><h1>Детальная страница вакансии</h1>
<main><p>Поделиться</p><h1>Технический директор</h1><p>Компания Лютик, Санкт-Петербург, гибрид.</p>{DESCRIPTION}
<script>var tracking = 1;</script><h2>Похожие вакансии</h2><p>Сметчик, Москва</p></main><footer>Подвал сайта</footer></body></html>"""

EMPTY_PAGE = "<html><head><title>Загрузка…</title></head><body><div id='app'></div><script src='app.js'></script></body></html>"


def fake_fields(prompt, model=None, options=None):
    lines = re.findall(r"(?m)^(\d+): ", prompt)
    return ("Название: Технический директор\nКомпания: ООО Лютик\nЗарплата: не указана\nГород: Санкт-Петербург\nФормат: гибрид"
            + (f"\nОписание: строки 2–{lines[-1]}" if lines else ""))


def no_model(*a, **k):
    raise AssistantError("Ollama не запущена")


class Sites(unittest.TestCase):
    def test_split_links(self):
        hh_ids, other = sites.split_links("https://hh.ru/vacancy/123456?from=x и https://job.example.ru/v/1?utm=2, "
                                          "ещё https://job.example.ru/v/1?utm=2")
        self.assertEqual((hh_ids, other), (["123456"], ["https://job.example.ru/v/1?utm=2"]))
        self.assertEqual(sites.split_links("123456"), (["123456"], []))                 # номер без ссылки — hh
        self.assertEqual(sites.key("https://www.Job.ru/v/1/?utm=1#top"), sites.key("https://job.ru/v/1"))

    def test_source_names(self):
        self.assertEqual(sites.source("https://spb.hh.ru/vacancy/1"), "HH")
        self.assertEqual(sites.source("https://career.habr.com/vacancies/1", "СберЗдоровье"), "Хабр Карьера")
        self.assertEqual(sites.source("https://job.mts.ru/vacancy/7", "ПАО МТС"), "Сайт МТС")      # сайт компании
        self.assertEqual(sites.source("https://jobs.example.com/x", "jobs.example.com"), "jobs.example.com")
        self.assertEqual(sites.source("нет — текст вставлен вручную"), "Вручную")
        self.assertEqual(sites.people_query("ПАО МТС"), "МТС")                              # поиск людей
        self.assertEqual(sites.people_query("Роял Кредит Банк (группа «Диалект»)"), "Роял Кредит Банк")
        self.assertEqual(sites.people_query("Анонимный работодатель"), "")

    def test_job_posting_markup(self):
        with TempProfile() as t:
            saved = sites.add_pages(t.profile, ["https://romashka.ru/jobs/cio"], log=lambda *_: None,
                                    fetch_page=lambda url: JOBPOSTING_PAGE, ask=no_model)
            text, info = read_vacancy(saved[0])
            self.assertEqual((info["title"], info["company"]), ("Директор по ИТ (CIO)", "ООО Ромашка"))
            self.assertEqual(info["salary"], "от 500 000 до 700 000 RUB в месяц")
            self.assertIn("**Где:** Москва", text)
            self.assertIn("- руководить ИТ-направлением", text)
            self.assertNotIn("Меню сайта", text)

    def test_job_posting_with_short_description(self):
        """В разметке вместо описания одна строка-аннотация: текст — со страницы, поля — из разметки."""
        page = JOBPOSTING_PAGE.replace(json.dumps(DESCRIPTION, ensure_ascii=False)[1:-1],
                                       "Вакансия Директор по ИТ, работа в компании Ромашка, в Москве.")
        page = page.replace("<h1>Директор по ИТ (CIO)</h1>", "<main><h1>Директор по ИТ (CIO)</h1>" + DESCRIPTION + "</main>")
        with TempProfile() as t:
            saved = sites.add_pages(t.profile, ["https://romashka.ru/jobs/cio"], log=lambda *_: None,
                                    fetch_page=lambda url: page, ask=no_model)
            text, info = read_vacancy(saved[0])
            self.assertEqual((info["title"], info["company"]), ("Директор по ИТ (CIO)", "ООО Ромашка"))
            self.assertEqual(info["salary"], "от 500 000 до 700 000 RUB в месяц")
            self.assertIn("- руководить ИТ-направлением", text)

    def test_plain_page_with_and_without_model(self):
        with TempProfile() as t:
            t.profile.llm_pages = True                                                   # человек разрешил модель
            lines = []
            saved = sites.add_pages(t.profile, ["https://lutik.ru/v/7"], log=lines.append,
                                    fetch_page=lambda url: PLAIN_PAGE, ask=fake_fields)
            text, info = read_vacancy(saved[0])
            self.assertEqual((info["title"], info["company"]), ("Технический директор", "ООО Лютик"))
            self.assertIn("Санкт-Петербург, гибрид", text)
            for junk in ("Шапка и меню", "Подвал сайта", "tracking", "Детальная страница", "Поделиться", "Сметчик"):
                self.assertNotIn(junk, text.split("---", 1)[1])
            self.assertTrue(any("убрала со страницы лишнее" in l for l in lines))
            # та же ссылка с хвостом — уже есть
            sites.add_pages(t.profile, ["https://lutik.ru/v/7?utm_source=tg"], log=lines.append,
                            fetch_page=lambda url: PLAIN_PAGE, ask=fake_fields)
            self.assertEqual(len(list(t.profile.vacancies.glob("*.md"))), 1)
        with TempProfile() as t:                                                        # модели нет — всё равно добавляем
            t.profile.llm_pages = True
            saved = sites.add_pages(t.profile, ["https://lutik.ru/v/7"], log=lambda *_: None,
                                    fetch_page=lambda url: PLAIN_PAGE, ask=no_model)
            text, info = read_vacancy(saved[0])
            self.assertEqual((info["title"], info["company"]), ("Технический директор", "lutik.ru"))
            self.assertNotIn("Сметчик", text)                                           # хвост отрезан и без модели
        with TempProfile() as t:                                                        # нет согласия — модель не зовём
            def forbidden(*a, **k):
                raise AssertionError("модель вызвана без согласия")
            lines = []
            saved = sites.add_pages(t.profile, ["https://lutik.ru/v/7"], log=lines.append,
                                    fetch_page=lambda url: PLAIN_PAGE, ask=forbidden)
            self.assertIn("Поделиться", read_vacancy(saved[0])[0])
            self.assertTrue(any("Параметры → Настройки" in l for l in lines))

    def test_model_wrong_line_numbers_keep_text(self):
        page = "Меню\n\n" + "Задачи: руководить ИТ. " * 30
        bad = lambda *a, **k: "Название: CIO\nОписание: строки 5–1"
        fields = sites.ask_fields(page, bad, cut=True)
        self.assertEqual(fields, {"title": "CIO"})

    def test_page_without_text_is_skipped(self):
        with TempProfile() as t:
            lines = []
            self.assertEqual(sites.add_pages(t.profile, ["https://spa.example/v/1"], log=lines.append,
                                             fetch_page=lambda url: EMPTY_PAGE, ask=no_model), [])
            self.assertTrue(any("вставив её текст" in l for l in lines))

    def test_pasted_text(self):
        with TempProfile() as t:
            t.profile.llm_pages = True
            path = sites.add_text(t.profile, "Технический директор\n\n" + "Обязанности: руководить разработкой. " * 5,
                                  "https://lutik.ru/v/9", log=lambda *_: None, ask=fake_fields)
            text, info = read_vacancy(path)
            self.assertEqual((info["title"], info["company"], info["link"]),
                             ("Технический директор", "ООО Лютик", "https://lutik.ru/v/9"))
            path = sites.add_text(t.profile, "Руководитель ИТ\n\n" + "Задачи: бюджет и команда. " * 6, log=lambda *_: None,
                                  ask=no_model)
            self.assertEqual(read_vacancy(path)[1]["title"], "Руководитель ИТ")                 # без модели — первая строка
            self.assertTrue(path.name.startswith("02 "))
            with self.assertRaises(AssistantError):
                sites.add_text(t.profile, "коротко", log=lambda *_: None)

    def test_refresh_keeps_number_and_date(self):
        with TempProfile() as t:
            path = sites.add_pages(t.profile, ["https://lutik.ru/v/7"], log=lambda *_: None,
                                   fetch_page=lambda url: PLAIN_PAGE, ask=fake_fields)[0]   # без согласия — целиком
            self.assertIn("Поделиться", read_text(path))
            t.profile.llm_pages = True                                                   # разрешили — обновляем
            write_text(path, re.sub(r"\*\*Сохранено:\*\* .*", "**Сохранено:** 01.10.2026", read_text(path)))
            self.assertTrue(sites.refresh(t.profile, path, log=lambda *_: None, fetch_page=lambda url: PLAIN_PAGE,
                                          ask=fake_fields))
            text, info = read_vacancy(path)
            self.assertNotIn("Поделиться", text)
            self.assertEqual((info["company"], info["saved"]), ("ООО Лютик", "01.10.2026"))
            self.assertEqual(len(list(t.profile.vacancies.glob("*.md"))), 1)
            lines = []                                                                   # сайт недоступен — текст прежний
            self.assertFalse(sites.refresh(t.profile, path, log=lines.append, fetch_page=lambda url: (_ for _ in ()).throw(
                AssistantError("Страницы больше нет (ответ 404) — вакансию, похоже, сняли."))))
            self.assertTrue(any("Оставляю прежний текст" in l for l in lines))

    def test_hh_links_still_work(self):
        with TempProfile() as t:
            saved = sites.add_any(t.profile, "https://hh.ru/vacancy/123456", log=lambda *_: None,
                                  fetch_page=lambda url: VACANCY_HTML)
            self.assertIn("hh.ru/vacancy/123456", read_text(saved[0]))


if __name__ == "__main__":
    unittest.main()
