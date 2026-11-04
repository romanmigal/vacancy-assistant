"""«Где искать вакансии» (#32): общий список ссылки.json, порядок по сфере профиля, свои ссылки."""
import json
import tempfile
import unittest
from pathlib import Path

from helpers import TempProfile, fake_model

from vacancy_assistant import app as A, links
from vacancy_assistant.errors import AssistantError
from vacancy_assistant.profile import Profile


class Builtin(unittest.TestCase):
    def test_file_is_valid(self):
        data = links.load_builtin()
        self.assertGreater(len(data["ссылки"]), 20)
        for item in data["ссылки"]:
            self.assertTrue(item["адрес"].startswith("https://"), item["название"])
            self.assertTrue(item["описание"].strip(), item["название"])
        names = [i["название"] for i in data["ссылки"]]
        self.assertEqual(len(names), len(set(names)))

    def test_bad_file(self):
        for item, error in (({"название": "А"}, "нет полей"),
                            ({"группа": "сайты", "название": "А", "адрес": "http://a.ru", "описание": "x", "сферы": [], "проверено": "2026-10-28"}, "не https"),
                            ({"группа": "нет", "название": "А", "адрес": "https://a.ru", "описание": "x", "сферы": [], "проверено": "2026-10-28"}, "неизвестная группа"),
                            ({"группа": "сайты", "название": "А", "адрес": "https://a.ru", "описание": "x", "сферы": ["Космос"], "проверено": "2026-10-28"}, "неизвестная сфера")):
            with tempfile.TemporaryDirectory() as d:
                path = Path(d) / "ссылки.json"
                path.write_text(json.dumps({"группы": [{"ключ": "сайты", "название": "Сайты"}], "ссылки": [item]}), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, error):
                    links.load_builtin(path)


class ForProfile(unittest.TestCase):
    def setUp(self):
        self.t = TempProfile().__enter__()
        self.app = A.App(self.t.profiles, fetch_page=lambda url: "", ask=fake_model,
                         check=lambda: {"ollama": True, "model_ok": True})

    def tearDown(self):
        self.t.__exit__(None, None, None)

    def call(self, path, method="POST", **data):
        if method == "GET":
            return self.app.handle("GET", path, {"profile": ["example"]}, {})
        return self.app.handle("POST", path, {}, {"profile": "example", **data})

    def test_it_profile_order(self):
        res = self.call("/api/links", "GET")
        self.assertEqual(res["spheres"], ["ИТ"])
        tg = next(g for g in res["groups"] if g["key"] == "telegram")
        self.assertEqual(res["groups"][0]["items"][0]["name"], "hh.ru")        # порядок — как в файле
        self.assertTrue(all(not i["spheres"] or "ИТ" in i["spheres"] for i in tg["items"]))
        self.assertTrue(all(not set(i["spheres"]) & {"ИТ"} for i in tg["other"]))
        self.assertIn("Бухджоб", [i["name"] for i in tg["other"]])             # чужая сфера — свёрнута
        self.assertTrue(all(i["auto"] for i in res["groups"][0]["items"]))   # у сайтов — как попасть в программу

    def test_finance_profile(self):
        p = Profile("example", self.t.profiles)
        p.config["разбор"]["для_кого"] = "специалистов и руководителей в сфере «финансы, бухгалтерия»"
        p.config["поиск"]["название_про_сферу"] = {"слова": [], "части": ["бухга"]}
        p.save_config()
        res = self.call("/api/links", "GET")
        self.assertEqual(res["spheres"], ["Финансы"])
        tg = next(g for g in res["groups"] if g["key"] == "telegram")
        self.assertEqual(tg["items"][0]["name"], "Бухджоб")
        self.assertNotIn("Get IT", [i["name"] for i in tg["items"]])

    def test_own_links(self):
        own = self.call("/api/links/save", do="add", name="  Чат  CIO ", url="https://t.me/cio_chat", about="знакомства")["own"]
        self.assertEqual([(i["название"], i["адрес"]) for i in own], [("Чат CIO", "https://t.me/cio_chat")])
        for name, url, error in (("", "https://a.ru", "Введите"), ("А", "t.me/x", "https://"),
                                 ("А", "javascript:alert(1)", "https://"), ("Б", "https://t.me/cio_chat/", "уже есть")):
            with self.assertRaisesRegex(AssistantError, error):
                self.call("/api/links/save", do="add", name=name, url=url)
        self.assertEqual(len(self.call("/api/links", "GET")["own"]), 1)
        self.call("/api/links/save", do="delete", id=own[0]["id"])
        self.assertEqual(self.call("/api/links", "GET")["own"], [])

    def test_favorites(self):
        self.assertEqual(self.call("/api/links/favorites", "GET")["favorites"], [{"name": "hh.ru", "url": "https://hh.ru"}])   # по умолчанию
        favs = self.call("/api/links/save", do="favorite", url="https://career.habr.com", on=True)["favorites"]
        self.assertEqual([f["name"] for f in favs], ["hh.ru", "Хабр Карьера"])
        self.call("/api/links/save", do="favorite", url="https://hh.ru", on=False)
        own = self.call("/api/links/save", do="add", name="Чат CIO", url="https://t.me/cio_chat")["own"]
        self.call("/api/links/save", do="favorite", url="https://t.me/cio_chat", on=True)
        res = self.call("/api/links", "GET")
        self.assertEqual(res["favorite_urls"], ["https://career.habr.com", "https://t.me/cio_chat"])
        with self.assertRaisesRegex(AssistantError, "нет в списке"):
            self.call("/api/links/save", do="favorite", url="https://evil.example", on=True)
        self.call("/api/links/save", do="delete", id=own[0]["id"])                    # удалили свою — ушла из любимых
        self.assertEqual(Profile("example", self.t.profiles).config["любимые_ссылки"], ["https://career.habr.com"])
        self.call("/api/links/save", do="favorite", url="https://career.habr.com", on=False)
        self.assertEqual(self.call("/api/links/favorites", "GET")["favorites"], [])   # пустой список — не hh снова


if __name__ == "__main__":
    unittest.main()
