"""Поиск на hh.ru — только с согласия (#28): выключен в новом профиле, без согласия не включить, прежний
профиль ждёт решения, без согласия нет запросов к hh.ru, дневной предел, сохранённая страница вакансии."""
import unittest
from datetime import date

from helpers import FIXTURES, SEARCH_HTML, TempProfile, VACANCY_HTML, fake_model, vacancy_page

from vacancy_assistant import app as A, hh, setup, sites
from vacancy_assistant.errors import AssistantError
from vacancy_assistant.profile import Profile
from vacancy_assistant.textio import read_json, read_text, write_json, write_text

ANSWERS = {"name": "Мария Иванова", "titles": "Главный бухгалтер", "resume": "# Резюме\n\nГлавный бухгалтер.",
           "city": "Москва", "salary": "250000"}
SAVED_HH = read_text(FIXTURES / "страницы" / "hh-вакансия.html")


def no_network(url):
    raise AssertionError(f"обращение к сети: {url}")


class Consent(unittest.TestCase):
    def setUp(self):
        self.t = TempProfile().__enter__()

    def tearDown(self):
        self.t.__exit__(None, None, None)

    def reload(self, name="example"):
        return Profile(name, self.t.profiles)

    def test_new_profile_off_and_consent(self):
        name = setup.create_profile(ANSWERS, self.t.profiles, log=lambda *_: None)
        p = self.reload(name)
        self.assertEqual((p.hh_state, p.hh_auto), ("off", False))                 # по умолчанию выключен
        self.assertEqual(p.config["hh_авто"], {"включено": False})
        with self.assertRaises(AssistantError):                                     # включить без согласия нельзя
            setup.create_profile({**ANSWERS, "name": "Анна", "hh_auto": True}, self.t.profiles, log=lambda *_: None)
        with self.assertRaises(AssistantError):
            setup.set_hh_auto(p, True)
        self.assertFalse(self.reload(name).hh_auto)
        setup.set_hh_auto(p, True, risk=True)
        self.assertEqual(self.reload(name).config["hh_авто"], {"включено": True, "согласие": date.today().isoformat()})
        on = setup.create_profile({**ANSWERS, "name": "Анна", "hh_auto": True, "hh_risk": True}, self.t.profiles,
                                  log=lambda *_: None)
        self.assertEqual(self.reload(on).config["hh_авто"]["согласие"], date.today().isoformat())   # дата согласия
        setup.set_hh_auto(p, False)
        self.assertEqual(self.reload(name).hh_state, "off")

    def test_off_blocks_hh_without_network(self):
        p = self.t.profile
        setup.set_hh_auto(p, False)
        with self.assertRaises(AssistantError) as e:
            hh.search(p, log=lambda *_: None, fetch_page=no_network, sleep=lambda s: None)
        self.assertIn("выключен", str(e.exception))
        with self.assertRaises(AssistantError):
            hh.add_vacancies(p, ["123456"], log=lambda *_: None, fetch_page=no_network)
        with self.assertRaises(AssistantError):
            sites.add_any(p, "https://hh.ru/vacancy/123456", lambda *_: None, no_network)
        for action, data in (("update", {}), ("add", {"links": "https://hh.ru/vacancy/123456"})):
            with self.assertRaises(AssistantError):                                 # отказ до запуска задачи
                A.make_work(p, action, data, no_network, fake_model)
        logs = []                                                                   # вместе с другим сайтом — hh пропускаем
        sites.add_any(p, "https://hh.ru/vacancy/123456 https://example.com/job/1", logs.append,
                      lambda url: "<html><body>пусто</body></html>" if "example" in url else no_network(url))
        self.assertTrue(any("пропускаю" in l for l in logs))

    def test_old_profile_waits_for_choice(self):
        p = self.t.profile
        p.config.pop("hh_авто")
        p.config["согласие_hh"] = "2026-01-10"                                      # так было в прежних версиях
        p.save_config()
        p = self.reload()
        self.assertEqual((p.hh_state, p.hh_auto), ("ask", False))
        with self.assertRaises(AssistantError) as e:
            hh.search(p, log=lambda *_: None, fetch_page=no_network, sleep=lambda s: None)
        self.assertIn("решения", str(e.exception))
        app = A.App(self.t.profiles)
        self.assertEqual(app.handle("GET", "/api/state", {"profile": ["example"]}, {})["hh"]["state"], "ask")
        app.handle("POST", "/api/profile/settings", {}, {"profile": "example", "hh_auto": True, "hh_risk": True})
        p = self.reload()
        self.assertEqual(p.hh_state, "on")
        self.assertNotIn("согласие_hh", p.config)

    def test_day_limit(self):
        p, calls = self.t.profile, []
        fetch = lambda url: calls.append(url) or vacancy_page(url)
        write_json(p.dir / hh.COUNTER_FILE, {"дата": date.today().isoformat(), "запросов": hh.DAY_LIMIT - 1})
        logs = []
        saved = hh.add_vacancies(p, ["123456", "654321"], log=logs.append, fetch_page=fetch)
        self.assertEqual((len(saved), len(calls)), (1, 1))                           # второй запрос — уже за пределом
        self.assertTrue(any("дневной предел" in l for l in logs))
        self.assertEqual(read_json(p.dir / hh.COUNTER_FILE)["запросов"], hh.DAY_LIMIT)
        with self.assertRaises(hh.DayLimit):
            hh.search(p, log=lambda *_: None, fetch_page=fetch, sleep=lambda s: None)
        write_json(p.dir / hh.COUNTER_FILE, {"дата": "2020-01-01", "запросов": hh.DAY_LIMIT})   # вчерашний счёт не мешает
        self.assertEqual(len(hh.add_vacancies(p, ["777777"], log=lambda *_: None, fetch_page=fetch)), 1)
        st = A.App(self.t.profiles).handle("GET", "/api/state", {"profile": ["example"]}, {})["hh"]
        self.assertEqual((st["state"], st["used"], st["limit"]), ("on", 1, hh.DAY_LIMIT))

    def test_day_limit_keeps_rest_for_next_search(self):
        p = self.t.profile
        write_text(p.searches, "CTO\n")
        pages = lambda url: SEARCH_HTML if "search" in url and "page=0" in url else (
            "" if "search" in url else vacancy_page(url))
        search_requests = 2 * len(p.search_where)                                  # первая страница и пустая вторая
        write_json(p.dir / hh.COUNTER_FILE, {"дата": date.today().isoformat(),
                                             "запросов": hh.DAY_LIMIT - search_requests - 1})   # хватит на одну вакансию
        logs = []
        first = hh.search(p, log=logs.append, fetch_page=pages, sleep=lambda s: None)
        self.assertEqual(len(first), 1)
        self.assertTrue(any("при следующем поиске" in l for l in logs))
        self.assertIn("111111\t", read_text(p.seen))
        self.assertNotIn("333333", read_text(p.seen))                              # не скачана — не «взята»
        write_json(p.dir / hh.COUNTER_FILE, {"дата": "2020-01-01", "запросов": hh.DAY_LIMIT})   # наступил новый день
        second = hh.search(p, log=lambda *_: None, fetch_page=pages, sleep=lambda s: None)
        self.assertEqual(len(second), 1)                                           # её взял следующий поиск
        self.assertIn("333333\t", read_text(p.seen))

    def test_saved_hh_page(self):
        p = self.t.profile
        setup.set_hh_auto(p, False)                                                  # страница — без сети и без согласия
        path = sites.add_saved(p, SAVED_HH, "вакансия.html", log=lambda *_: None)
        text = read_text(path)
        self.assertIn("# Директор по ИТ", text)
        self.assertIn("**Компания:** ООО Пример", text)
        self.assertIn("**Ссылка:** https://hh.ru/vacancy/987654321", text)          # номер — из адреса страницы
        self.assertIn("- опыт внедрения ERP.", text)
        self.assertNotIn("Похожие вакансии", text)
        self.assertIn("987654321\t", read_text(p.seen))                               # поиск не возьмёт её снова
        with self.assertRaises(AssistantError):                                      # та же страница ещё раз
            sites.add_saved(p, SAVED_HH, log=lambda *_: None)
        bare = SAVED_HH.replace("<!-- saved from url=(0031)https://hh.ru/vacancy/987654321 -->", "") \
                       .replace('<link rel="canonical" href="https://hh.ru/vacancy/987654321">', "") \
                       .replace('<meta property="og:url" content="https://hh.ru/vacancy/987654321">', "")
        self.assertEqual(sites.hh_page_id(bare, sites.page_url(bare)), "987654321")   # из данных страницы
        with self.assertRaises(AssistantError):
            A.make_work(p, "add_page", {"page": "не страница"}, no_network, fake_model)

    def test_saved_other_site(self):
        page = ('<html><head><link rel="canonical" href="https://career.example.com/jobs/42"></head><body><main>'
                '<h1>Финансовый директор</h1>' + "<p>Отвечать за финансы группы компаний и бюджет.</p>" * 12
                + "</main></body></html>")
        path = sites.add_saved(self.t.profile, page, log=lambda *_: None)
        self.assertIn("**Ссылка:** https://career.example.com/jobs/42", read_text(path))
        with self.assertRaises(AssistantError):
            sites.add_saved(self.t.profile, page, log=lambda *_: None)


if __name__ == "__main__":
    unittest.main()
