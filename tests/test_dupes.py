"""Склейка дублей (#13): та же вакансия с разных сайтов — одна карточка, ссылка в «Ещё ссылки»."""
import unittest
from pathlib import Path

from helpers import TempProfile

from vacancy_assistant import app as A, dupes, hh, sites
from vacancy_assistant.files import numbered_files, read_vacancy
from vacancy_assistant.textio import read_text, write_text

HH_PAGE = read_text(Path(__file__).parent / "fixtures" / "страницы" / "hh-вакансия.html")   # Директор по ИТ, ООО Пример
TEXT = ("Чем предстоит заниматься: руководить ИТ-службой и бюджетом ИТ; строить команду и процессы; отвечать за "
        "цифровую трансформацию. Мы ждём: опыт руководства ИТ от 5 лет; опыт внедрения ERP. Офис в центре Москвы.")
OTHER = ("Задачи: развитие интернет-магазина, маркетплейсы, логистика последней мили, программа лояльности. "
         "Требования: e-commerce от 7 лет, управление P&L, запуск мобильного приложения, аналитика продаж.")
quiet = lambda *_: None


def info(title, company="ООО Пример", text=TEXT):
    return {"title": title, "company": company, "salary": "", "where": "Москва", "format": "", "text": text}


class Find(unittest.TestCase):
    def test_same_from_other_site(self):
        """Та же вакансия с сайта компании после hh — ссылка дописана к прежней, новой карточки нет."""
        with TempProfile() as t:
            first = hh.add_vacancies(t.profile, ["987654321"], log=quiet, fetch_page=lambda url: HH_PAGE)[0]
            logs = []
            again = sites.save(t.profile, info("Директор по ИТ", "Пример"), "https://example.ru/jobs/cio", logs.append)
            self.assertIsNone(again)
            self.assertEqual(len(numbered_files(t.profile.vacancies)), 1)
            self.assertIn("Ещё ссылки:** https://example.ru/jobs/cio", read_text(first))
            self.assertIn("добавил ссылку", logs[-1])
            row = A.vacancy_rows(t.profile)[0]
            self.assertEqual(row["more_links"][0]["url"], "https://example.ru/jobs/cio")
            self.assertNotIn("Ещё ссылки", A.without_saved(read_text(first)))

    def test_hh_after_site(self):
        """Наоборот: сначала сайт компании, потом та же вакансия на hh — hh-ссылка в «Ещё ссылки»."""
        with TempProfile() as t:
            first = sites.save(t.profile, info("ИТ-директор", "ООО «Пример»"), "https://example.ru/jobs/cio", quiet)
            self.assertEqual(hh.add_vacancies(t.profile, ["987654321"], log=quiet, fetch_page=lambda url: HH_PAGE), [])
            self.assertIn("https://hh.ru/vacancy/987654321", read_text(first))
            self.assertEqual(read_vacancy(first)[1]["link"], "https://example.ru/jobs/cio")

    def test_different_roles(self):
        """Разные должности одной компании — не дубли."""
        with TempProfile() as t:
            sites.save(t.profile, info("CIO"), "https://example.ru/1", quiet)
            self.assertIsNotNone(sites.save(t.profile, info("Руководитель отдела ИТ"), "https://example.ru/2", quiet))
            self.assertIsNotNone(sites.save(t.profile, info("Директор по ИТ", "ООО Другая"), "https://example.ru/3", quiet))
            self.assertEqual(len(numbered_files(t.profile.vacancies)), 3)
            self.assertFalse(any(read_vacancy(p)[1]["maybe"] for p in numbered_files(t.profile.vacancies).values()))

    def test_old_not_compared(self):
        with TempProfile() as t:
            path = t.add_vacancy(1, "Директор по ИТ", "ООО Пример", saved="01.06.2026")
            write_text(path, read_text(path) + TEXT + "\n")
            self.assertIsNotNone(sites.save(t.profile, info("Директор по ИТ"), "https://example.ru/1", quiet))


class SameSite(unittest.TestCase):
    """С одного сайта: тот же город и тот же текст — дубль (работодатель опубликовал вакансию ещё раз)."""

    def test_republished_on_hh(self):
        with TempProfile() as t:
            pages = lambda url: HH_PAGE
            saved = hh.add_vacancies(t.profile, ["139092183", "139092184", "139092185"], log=quiet, fetch_page=pages)
            self.assertEqual(len(saved), 1)
            more = dupes.more_links(read_text(saved[0]))
            self.assertEqual(more, ["https://hh.ru/vacancy/139092184", "https://hh.ru/vacancy/139092185"])

    def test_other_city_is_not_dupe(self):
        with TempProfile() as t:
            pages = lambda url: HH_PAGE.replace(">Москва<", ">Екатеринбург<") if "222222" in url else HH_PAGE
            self.assertEqual(len(hh.add_vacancies(t.profile, ["111111", "222222"], log=quiet, fetch_page=pages)), 2)

    def test_other_text_is_not_dupe(self):
        """Разные вакансии одной компании на одном сайте — без пометки «Возможно, дубль»."""
        with TempProfile() as t:
            sites.save(t.profile, info("Директор по ИТ"), "https://example.ru/1", quiet)
            second = sites.save(t.profile, info("Директор по ИТ", text=OTHER), "https://example.ru/2", quiet)
            self.assertIsNotNone(second)
            self.assertEqual(read_vacancy(second)[1]["maybe"], "")


class Maybe(unittest.TestCase):
    def setUp(self):
        self.t = TempProfile().__enter__()
        self.first = sites.save(self.t.profile, info("Директор по ИТ"), "https://example.ru/1", quiet)
        self.second = sites.save(self.t.profile, info("Директор по ИТ", text=OTHER), "https://other.ru/2", quiet)
        self.trashed = []
        self.app = A.App(self.t.profiles, fetch_page=None, ask=None, check=lambda: {"ollama": True, "model_ok": True})
        self.app.trash = self.trashed.append

    def tearDown(self):
        self.t.__exit__(None, None, None)

    def test_marked(self):
        self.assertEqual(read_vacancy(self.second)[1]["maybe"], "1")
        self.assertEqual({r["n"]: r["maybe_dupe"] for r in A.vacancy_rows(self.t.profile)}, {1: None, 2: 1})

    def test_merge(self):
        write_text(self.t.profile.results / self.second.name, "разбор")
        r = self.app.handle("POST", "/api/dupe", {}, {"profile": "example", "n": 2, "action": "merge"})
        self.assertEqual(r["n"], 1)
        self.assertIn("https://other.ru/2", read_text(self.first))
        self.assertEqual([p.name for p in self.trashed], [self.second.name, self.second.name])   # разбор и вакансия

    def test_apart(self):
        self.app.handle("POST", "/api/dupe", {}, {"profile": "example", "n": 2, "action": "apart"})
        self.assertEqual(read_vacancy(self.second)[1]["maybe"], "")
        self.assertEqual(self.trashed, [])

    def test_add_link_once(self):
        self.assertTrue(dupes.add_link(self.first, "https://x.ru/1"))
        self.assertFalse(dupes.add_link(self.first, "https://x.ru/1"))
        self.assertFalse(dupes.add_link(self.first, "https://example.ru/1"))       # основная ссылка
        self.assertEqual(read_text(self.first).count("Ещё ссылки"), 1)


if __name__ == "__main__":
    unittest.main()
