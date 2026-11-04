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


if __name__ == "__main__":
    unittest.main()
