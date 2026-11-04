"""Свои статусы: до пяти вкладок перед «Архивом» — добавление, лимит, переименование, удаление с переносом,
Сводка.md, «История», резервная копия."""
import unittest

from helpers import TempProfile, fake_model

from vacancy_assistant import analysis, app as A, backup, funnel, summary as S
from vacancy_assistant.profile import Profile
from vacancy_assistant.textio import read_text


class Statuses(unittest.TestCase):
    def setUp(self):
        self.t = TempProfile().__enter__()
        for n in (1, 2):
            self.t.add_vacancy(n, f"ИТ-директор {n}")
        analysis.analyze(self.t.profile, log=lambda *_: None, ask=fake_model)
        self.app = A.App(self.t.profiles, fetch_page=lambda url: "", ask=fake_model,
                         check=lambda: {"ollama": True, "model_ok": True})

    def tearDown(self):
        self.t.__exit__(None, None, None)

    def call(self, path, **data):
        return self.app.handle("POST", path, {}, {"profile": "example", **data})

    def state(self):
        return self.app.handle("GET", "/api/state", {"profile": ["example"]}, {})

    def keys(self):
        return [k for k, _ in self.state()["statuses"]]

    def test_add_limit_and_checks(self):
        self.assertEqual(self.keys(), ["new", "yes", "interview", "no"])             # старый профиль — как прежде
        self.call("/api/statuses", do="add", name="Отложено")
        self.call("/api/statuses", do="add", name="  Думаю  ")
        self.assertEqual(list(self.state()["statuses"][3:]), [("c1", "Отложено"), ("c2", "Думаю"), ("no", "Архив")])
        self.assertEqual(self.state()["custom_statuses"], ["c1", "c2"])
        for name, error in (("", "Введите"), ("отложено", "уже есть"), ("архив", "уже есть"), ("x" * 21, "не длиннее")):
            with self.assertRaisesRegex(S.AssistantError, error):
                self.call("/api/statuses", do="add", name=name)
        for name in ("Третий", "Четвёртый", "Пятый"):
            self.call("/api/statuses", do="add", name=name)
        with self.assertRaisesRegex(S.AssistantError, "не больше 5"):
            self.call("/api/statuses", do="add", name="Шестой")
        p = Profile("example", self.t.profiles)                                        # после перезапуска — на месте
        self.assertEqual([n for _, n in p.custom_statuses], ["Отложено", "Думаю", "Третий", "Четвёртый", "Пятый"])

    def test_colors(self):
        self.call("/api/statuses", do="add", name="Отложено")                          # по умолчанию — первый свободный
        self.call("/api/statuses", do="add", name="Думаю", color="orange")
        self.call("/api/statuses", do="add", name="Третий")
        self.assertEqual(self.state()["status_colors"], {"c1": "blue", "c2": "orange", "c3": "violet"})
        with self.assertRaisesRegex(S.AssistantError, "Неизвестный цвет"):
            self.call("/api/statuses", do="add", name="Четвёртый", color="red")
        self.call("/api/statuses", do="color", key="c3", color="pink")                 # сменить цвет созданного
        self.assertEqual(self.state()["status_colors"]["c3"], "pink")
        with self.assertRaisesRegex(S.AssistantError, "Неизвестный цвет"):
            self.call("/api/statuses", do="color", key="c3", color="red")
        with self.assertRaisesRegex(S.AssistantError, "встроенных"):
            self.call("/api/statuses", do="color", key="yes", color="blue")
        self.call("/api/statuses", do="rename", key="c2", name="Позже")                # цвет при переименовании — тот же
        self.call("/api/statuses", do="delete", key="c1")
        self.assertEqual(Profile("example", self.t.profiles).status_colors, {"c2": "orange", "c3": "pink"})
        p = Profile("example", self.t.profiles)                                        # профиль без цветов (до этой версии)
        p.config["статусы"] = [{"ключ": "c1", "название": "А"}, {"ключ": "c2", "название": "Б", "цвет": "blue"}]
        p.save_config()
        self.assertEqual(Profile("example", self.t.profiles).status_colors, {"c1": "blue", "c2": "blue"})

    def test_status_summary_history_rename(self):
        self.call("/api/statuses", do="add", name="Отложено")
        self.call("/api/status", n=1, value="c1")
        self.assertEqual({r["n"]: r["status"] for r in self.state()["rows"]}, {1: "c1", 2: "new"})
        text = read_text(self.t.profile.summary)
        self.assertLess(text.index("## Отложено (1)"), text.index("## Архив (0)"))     # своя таблица перед «Архивом»
        self.assertIn("option(c1, отложено)", text)                                    # и в списке Meta Bind
        result = next(self.t.profile.results.glob("01 *.md"))
        self.assertEqual(funnel.read(result)["statuses"][-1]["status"], "Отложено")    # «История» — названием
        self.call("/api/statuses", do="rename", key="c1", name="Позже")
        self.assertIn(("c1", "Позже"), self.state()["statuses"])
        self.assertEqual(S.read_statuses(Profile("example", self.t.profiles))["s1"], "c1")   # вакансия осталась в нём
        self.assertEqual(funnel.read(result)["statuses"][-1]["status"], "Отложено")    # в истории — прежнее название
        with self.assertRaisesRegex(S.AssistantError, "Встроенные"):
            self.call("/api/statuses", do="rename", key="yes", name="Да")
        with self.assertRaisesRegex(S.AssistantError, "Встроенные"):
            self.call("/api/statuses", do="delete", key="no")

    def test_delete_moves_vacancies(self):
        self.call("/api/statuses", do="add", name="Отложено")
        self.call("/api/status", n=1, value="c1")
        self.call("/api/status", n=2, value="c1")
        res = self.call("/api/statuses", do="delete", key="c1", move_to="yes")
        self.assertEqual(res["moved"], 2)
        self.assertEqual(self.keys(), ["new", "yes", "interview", "no"])
        self.assertEqual({r["status"] for r in self.state()["rows"]}, {"yes"})
        result = next(self.t.profile.results.glob("01 *.md"))
        self.assertEqual(funnel.read(result)["statuses"][-1]["status"], "yes")         # перенос — в «Истории»
        self.assertNotIn("статусы", Profile("example", self.t.profiles).config)       # пустой список не хранится

    def test_order(self):
        for name in ("Отложено", "Думаю", "Третий"):
            self.call("/api/statuses", do="add", name=name)
        self.call("/api/statuses", do="order", keys=["c3", "c1", "c2"])
        self.assertEqual(self.keys(), ["new", "yes", "interview", "c3", "c1", "c2", "no"])
        for keys in (["c1", "c2"], ["c1", "c1", "c2"], ["c1", "c2", "yes"], "c1"):     # не все, повтор, чужой
            with self.assertRaisesRegex(S.AssistantError, "устарел"):
                self.call("/api/statuses", do="order", keys=keys)
        self.call("/api/statuses", do="delete", key="c1")
        self.call("/api/statuses", do="add", name="Новый")                              # свободный ключ c1 — в конец
        self.assertEqual(self.keys()[3:], ["c3", "c2", "c1", "no"])

    def test_unknown_status_is_new(self):
        S.set_status(self.t.profile, "s1", "c2")                                       # вписали руками в Obsidian
        self.assertEqual(S.read_statuses(self.t.profile)["s1"], "new")

    def test_backup_keeps_statuses(self):
        self.call("/api/statuses", do="add", name="Отложено")
        name = backup.restore(self.t.profiles, backup.make(Profile("example", self.t.profiles)))
        self.assertEqual(Profile(name, self.t.profiles).custom_statuses, [("c1", "Отложено")])


if __name__ == "__main__":
    unittest.main()
