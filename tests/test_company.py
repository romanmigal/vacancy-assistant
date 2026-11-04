"""О компании: агентство, рейтинг работодателя hh, прошлые вакансии в компании."""
import unittest

from helpers import VACANCY_HTML, TempProfile

from vacancy_assistant import app as A, company, hh, setup, sites
from datetime import date
from vacancy_assistant.errors import AssistantError
from vacancy_assistant.files import read_vacancy
from vacancy_assistant.textio import read_text

# Страница, сохранённая из браузера: виджет отзывов уже нарисован; данные страницы — с &#34; вместо кавычек
SAVED = VACANCY_HTML.replace('<a data-qa="vacancy-company-name">',
                             '<a data-qa="vacancy-company-name" href="/employer/2804?hhtmFrom=vacancy">') + """
<div data-qa="employer-review-small-widget-total-rating" class="x">4,2</div>
<div class="r" data-qa="employer-review-small-widget-review-count-action"><div><button><span>41&nbsp;отзыв</span></button></div></div>
<template>{&#34;trusted&#34;:true,&#34;category&#34;:&#34;AGENCY&#34;,&#34;visibleName&#34;:&#34;Пример&#34;,&#34;companySiteUrl&#34;:&#34;www.primer.ru&#34;,&#34;accreditedITEmployer&#34;:true}</template>"""
SAVED_PAGE = SAVED.replace("<body>", '<body><link rel="canonical" href="https://hh.ru/vacancy/555">', 1) + "x" * 500


class Employer(unittest.TestCase):
    def test_saved_page(self):
        self.assertEqual(company.hh_employer(SAVED), {"id": "2804", "category": "AGENCY", "rating": 4.2, "reviews": 41,
                                                     "site": "https://www.primer.ru", "it": True})

    def test_downloaded_page(self):
        """Скачанная программой страница: рейтинга нет (hh рисует его в браузере), номер работодателя есть."""
        page = SAVED.split('<div data-qa="employer-review')[0] + '<script>{"companySiteUrl":"http://servplus.ru"}</script>'
        self.assertEqual(company.hh_employer(page), {"id": "2804", "category": None, "rating": None, "reviews": None,
                                                     "site": "http://servplus.ru", "it": None})
        self.assertIsNone(company.hh_employer(VACANCY_HTML))             # работодатель скрыт

    def test_header_not_in_model_text(self):
        """В шапке вакансии — только ссылка на работодателя; рейтинг в текст (а значит и в модель) не попадает."""
        text = hh.vacancy_markdown(SAVED, "555")[2]
        self.assertIn("**Работодатель на hh:** https://hh.ru/employer/2804", text)
        self.assertNotIn("4,2", text)
        self.assertNotIn("отзыв", text)


EMPLOYER_PAGE = """<script>{&#34;companySiteUrl&#34;:&#34;www.primer.ru&#34;,&#34;reviews&#34;:[{&#34;id&#34;:&#34;1&#34;,
&#34;totalRating&#34;:&#34;5&#34;,&#34;ratings&#34;:[]}],&#34;reviewsAreHidden&#34;:false,&#34;reviewsCount&#34;:41,
&#34;totalRating&#34;:&#34;4.2&#34;,&#34;services&#34;:{},&#34;employerInfo&#34;:{&#34;accreditedITEmployer&#34;:false}}</script>"""


class Rating(unittest.TestCase):
    def test_employer_page(self):
        """Общий рейтинг — после списка отзывов, а не рейтинг первого отзыва."""
        self.assertEqual(company.employer_rating(EMPLOYER_PAGE), {"rating": 4.2, "reviews": 41, "site": "https://www.primer.ru", "it": False})
        self.assertEqual(company.employer_rating("<html></html>"), {"rating": None, "reviews": None, "site": None, "it": None})

    def test_fetch_only_with_search_and_monthly(self):
        with TempProfile() as t:
            asked = []
            get = lambda url: asked.append(url) or EMPLOYER_PAGE
            setup.set_hh_auto(t.profile, False)
            company.fetch_rating(t.profile, "2804", get, print)
            self.assertEqual(asked, [])                                          # поиск на hh выключен — не ходим
            setup.set_hh_auto(t.profile, True, risk=True)
            company.fetch_rating(t.profile, "2804", get, lambda *_: None, today=date(2026, 10, 1))
            self.assertEqual(asked, ["https://hh.ru/employer/2804"])
            self.assertEqual(company.load(t.profile)["hh"]["2804"]["rating"], 4.2)
            self.assertIs(company.load(t.profile)["hh"]["2804"]["it"], False)
            company.fetch_rating(t.profile, "2804", get, lambda *_: None, today=date(2026, 10, 20))
            self.assertEqual(len(asked), 1)                                       # свежий — не перечитываем
            company.fetch_rating(t.profile, "2804", get, lambda *_: None, today=date(2026, 11, 5))
            self.assertEqual(len(asked), 2)


class Site(unittest.TestCase):
    def test_site(self):
        self.assertEqual(company._site("www.x.ru"), "https://www.x.ru")
        self.assertEqual(company._site("https:\\/\\/x.ru\\/about"), "https://x.ru/about")
        self.assertIsNone(company._site("нет"))


class Agency(unittest.TestCase):
    EMPTY = {"agency": {}, "hh": {}}

    def check(self, name, text="", data=None):
        return company.agency(data or self.EMPTY, name, "# T\n\n**Компания:** x\n\n---\n\n" + text)[:2]

    def test_names(self):
        for name in ("Кадровое агентство Перспектива", "Hays", "ANCOR", "Antal Russia", "Star-Staff", "StaffRecruitment",
                     "Korn Ferry", "Get Experts", "Executive Search Group", "Рекрутинговая компания Профи"):
            with self.subTest(name):
                self.assertEqual(self.check(name), (True, "name"))

    def test_text(self):
        for text in ("Для нашего клиента — крупного банка — ищем CIO.", "Наш клиент — лидер рынка ритейла.",
                     "Компания-клиент: международный холдинг", "Работаем по поручению клиента."):
            with self.subTest(text):
                self.assertEqual(self.check("ООО Северный Ветер", text), (True, "text"))

    def test_not_agency(self):
        """Ложные срабатывания: кадровый резерв, работа с клиентами, HR-директор, Staffcop — компания-разработчик."""
        for name, text in (("Сбер", "Кадровый резерв, работа с клиентами, рост наших клиентов."),
                           ("ООО Ромашка", "Ищем HR-директора. Клиенты — наши партнёры."),
                           ("Staffcop", "Разработка ПО"), ("МТС", "Клиентский сервис")):
            with self.subTest(name):
                self.assertEqual(self.check(name, text), (False, ""))

    def test_order(self):
        """Ваша пометка главнее всего; признак hh главнее названия и текста."""
        data = {"agency": {}, "hh": {"7": {"category": "AGENCY"}}}
        self.assertEqual(company.agency(data, "Ромашка", "", "7")[:2], (True, "hh"))
        data["agency"] = {"romashka": False}
        self.assertEqual(company.agency(data, "ООО «Ромашка»", "Для нашего клиента", "7")[:2], (False, "mark"))


class About(unittest.TestCase):
    def test_past_and_mark(self):
        with TempProfile() as t:
            t.add_vacancy(1, "ИТ-директор", "ООО Ромашка")
            t.add_vacancy(2, "CIO", "Ромашка")
            t.add_vacancy(3, "CTO", "Ромашка Финанс")
            t.add_vacancy(4, "CDO", "Лесная Компания")
            a = company.about(t.profile, 1)
            self.assertEqual(a["past"], [{"n": 2, "exact": True}, {"n": 3, "exact": False}])   # похожее — с «?»
            self.assertEqual((a["agency"], a["hh"]), (False, None))
            company.set_mark(t.profile, "Ромашка", True)
            rows = {r["n"]: r for r in A.vacancy_rows(t.profile)}
            self.assertEqual([rows[n]["agency"] for n in (1, 2, 3, 4)], [True, True, False, False])   # на всю компанию
            self.assertEqual(rows[1]["agency_why"], "mark")
            company.set_mark(t.profile, "Ромашка", None)
            self.assertFalse(company.about(t.profile, 2)["agency"])

    def test_saved_page_again_updates_rating(self):
        """Вакансия уже в списке (скачана без рейтинга) — та же страница из браузера добавляет рейтинг и ссылку."""
        with TempProfile() as t:
            path = t.add_vacancy(5, "ИТ-директор", "Пример")
            path.write_text(read_text(path).replace("vacancy/100005", "vacancy/555"), encoding="utf-8")
            with self.assertRaisesRegex(AssistantError, "уже есть в списке под номером 05. Рейтинг"):
                sites.add_saved(t.profile, SAVED_PAGE, log=lambda *_: None)
            self.assertEqual(read_vacancy(path)[1]["employer"], "https://hh.ru/employer/2804")
            a = company.about(t.profile, 5)
            self.assertEqual((a["hh"]["rating"], a["hh"]["reviews"], a["hh"]["site"], a["agency"], a["agency_why"]),
                             (4.2, 41, "https://www.primer.ru", True, "hh"))
            # позже скачанная программой страница без рейтинга прежний рейтинг не стирает
            company.remember_hh(t.profile, {"id": "2804", "category": None, "rating": None, "reviews": None}, "Пример")
            self.assertEqual(company.about(t.profile, 5)["hh"]["rating"], 4.2)
            self.assertIs(company.about(t.profile, 5)["hh"]["it"], True)          # и ИТ-аккредитация

    def test_route(self):
        with TempProfile() as t:
            t.add_vacancy(1, "ИТ-директор", "Hays")
            app = A.App(t.profiles, fetch_page=None, ask=None, check=lambda: {"ollama": True, "model_ok": True})
            self.assertTrue(app.handle("GET", "/api/vacancy", {"profile": ["example"], "n": ["1"]}, {})["about"]["agency"])
            app.handle("POST", "/api/company/agency", {}, {"profile": "example", "n": 1, "agency": False})
            self.assertEqual(company.about(t.profile, 1)["agency_why"], "mark")


class Companies(unittest.TestCase):
    def test_list(self):
        """Разные написания одной компании — одна строка; скрытый работодатель — отдельно; пометка — общая с карточкой."""
        with TempProfile() as t:
            t.add_vacancy(1, "ИТ-директор", "ООО Ромашка")
            t.add_vacancy(2, "CIO", "«Ромашка»")
            t.add_vacancy(3, "CTO", "Hays")
            t.add_vacancy(4, "CDO", "Анонимный работодатель")
            app = A.App(t.profiles, fetch_page=None, ask=None, check=lambda: {"ollama": True, "model_ok": True})
            res = app.handle("GET", "/api/companies", {"profile": ["example"]}, {})
            by = {c["name"]: c for c in res["items"]}
            self.assertEqual(sorted(by), ["Hays", "«Ромашка»"])
            self.assertEqual(by["«Ромашка»"]["vacancies"], [2, 1])                 # свежие первыми
            self.assertEqual(by["«Ромашка»"]["names"], ["«Ромашка»", "ООО Ромашка"])
            self.assertEqual((by["Hays"]["agency"], by["Hays"]["agency_why"]), (True, "name"))
            self.assertFalse(by["«Ромашка»"]["agency"])
            self.assertEqual(res["anonymous"], [4])
            self.assertIn("bo.nalog.gov.ru", by["Hays"]["finance"]["url"])
            app.handle("POST", "/api/company/agency", {}, {"profile": "example", "n": by["«Ромашка»"]["n"], "agency": True})
            again = {c["name"]: c for c in company.companies(t.profile, A.vacancy_rows(t.profile))["items"]}
            self.assertEqual((again["«Ромашка»"]["agency"], again["«Ромашка»"]["marked"]), (True, True))
            self.assertTrue(company.about(t.profile, 1)["agency"])               # и в карточке вакансии

    def test_hh_and_site(self):
        with TempProfile() as t:
            path = t.add_vacancy(5, "ИТ-директор", "Пример")
            path.write_text(read_text(path).replace("vacancy/100005", "vacancy/555"), encoding="utf-8")
            with self.assertRaises(AssistantError):
                sites.add_saved(t.profile, SAVED_PAGE, log=lambda *_: None)
            c = company.companies(t.profile, A.vacancy_rows(t.profile))["items"][0]
            self.assertEqual((c["hh"]["url"], c["hh"]["rating"], c["hh"]["reviews"], c["hh"]["it"], c["site"]),
                             ("https://hh.ru/employer/2804", 4.2, 41, True, "https://www.primer.ru"))

    def test_empty(self):
        with TempProfile() as t:
            self.assertEqual(company.companies(t.profile, []), {"items": [], "anonymous": []})


if __name__ == "__main__":
    unittest.main()
