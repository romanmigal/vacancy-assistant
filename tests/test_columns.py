"""Колонки таблицы в окне: порядок и скрытые хранятся в профиле и приходят в /api/state."""
import unittest

from helpers import TempProfile

from vacancy_assistant import app as A
from vacancy_assistant.profile import CONFIG_FILE, Profile
from vacancy_assistant.textio import read_json, write_json


class Columns(unittest.TestCase):
    def setUp(self):
        self.t = TempProfile().__enter__()
        self.t.add_vacancy(1, "Директор по ИТ")
        self.app = A.App(self.t.profiles)

    def tearDown(self):
        self.t.__exit__(None, None, None)

    def state(self):
        return self.app.handle("GET", "/api/state", {"profile": ["example"]}, {})

    def save(self, columns):
        return self.app.handle("POST", "/api/profile/settings", {}, {"profile": "example", "columns": columns})

    def test_default_empty(self):
        self.assertEqual(self.state()["columns"], {"order": [], "hidden": []})
        self.assertNotIn("колонки", read_json(self.t.profile.dir / CONFIG_FILE))

    def test_save_and_reload(self):
        self.save({"order": ["title", "stage", "score"], "hidden": ["source", "note"]})
        self.assertEqual(self.state()["columns"], {"order": ["title", "stage", "score"], "hidden": ["source", "note"]})
        config = read_json(self.t.profile.dir / CONFIG_FILE)
        self.assertEqual(config["колонки"], {"порядок": ["title", "stage", "score"], "скрыты": ["source", "note"]})
        self.assertEqual(Profile("example", self.t.profiles).columns["hidden"], ["source", "note"])   # после перезапуска
        self.save({"order": [], "hidden": []})                                          # «Как было»
        self.assertNotIn("колонки", read_json(self.t.profile.dir / CONFIG_FILE))

    def test_garbage_dropped(self):
        self.save({"order": ["title", "title", "../x", 5, "Оценка", "a" * 50], "hidden": "note"})
        self.assertEqual(self.state()["columns"], {"order": ["title"], "hidden": []})
        config = read_json(self.t.profile.dir / CONFIG_FILE)
        write_json(self.t.profile.dir / CONFIG_FILE, {**config, "колонки": "сломано"})          # правили руками
        self.assertEqual(Profile("example", self.t.profiles).columns, {"order": [], "hidden": []})



class SavedFilters(Columns):
    """Сохранённые фильтры вкладки «Фильтр»: список целиком в профиле, мусор отбрасывается."""

    def save(self, items):
        return self.app.handle("POST", "/api/profile/settings", {}, {"profile": "example", "saved_filters": items})

    def test_default_empty(self):
        self.assertEqual(self.state()["saved_filters"], [])

    def test_save_and_reload(self):
        item = {"name": "Плати по всему миру после 20.09", "closed": False,
                "f": {"company": {"only": ["Плати по всему миру"]}, "posted": {"from": "2026-09-20"}}}
        self.save([item])
        self.assertEqual(self.state()["saved_filters"], [item])
        self.assertEqual(read_json(self.t.profile.dir / CONFIG_FILE)["фильтры"], [item])
        self.assertEqual(Profile("example", self.t.profiles).saved_filters, [item])          # после перезапуска
        self.save([])
        self.assertNotIn("фильтры", read_json(self.t.profile.dir / CONFIG_FILE))

    def test_garbage_dropped(self):
        self.save([{"name": "  Один   фильтр ", "f": {"company": {"out": ["А"]}, "../x": {}, "note": "строка"}, "closed": 1},
                   {"name": "один фильтр", "f": {}},                       # то же имя — второй не берём
                   {"name": "", "f": {}}, {"name": "Без условий"}, "мусор",
                   {"name": "Огромный", "f": {"title": {"text": "x" * 30000}}}])
        self.assertEqual(self.state()["saved_filters"], [{"name": "Один фильтр", "f": {"company": {"out": ["А"]}}, "closed": True}])
        self.save([{"name": f"Ф{i}", "f": {}} for i in range(30)])
        self.assertEqual(len(self.state()["saved_filters"]), 20)


if __name__ == "__main__":
    unittest.main()
