"""Шаблоны сопроводительного письма и отметка «Отправлено» (#53)."""
import shutil
import unittest

from helpers import TempProfile, fake_model

from vacancy_assistant import analysis, app as A, criteria_history, letter_templates as T
from vacancy_assistant.errors import AssistantError
from vacancy_assistant.profile import Profile
from vacancy_assistant.textio import read_text


class Templates(unittest.TestCase):
    def setUp(self):
        self.t = TempProfile().__enter__()
        self.t.add_vacancy(1, "ИТ-директор")
        self.app = A.App(self.t.profiles, fetch_page=lambda url: "", ask=fake_model,
                         check=lambda: {"ollama": True, "model_ok": True})
        self.trashed = []
        self.app.trash = lambda path: (self.trashed.append(path.name), shutil.rmtree(path) if path.is_dir() else path.unlink())
        analysis.full_analysis(self.p(), self.path(), ask=fake_model, log=lambda *_: None)
        self.result = self.p().results / self.path().name

    def tearDown(self):
        self.t.__exit__(None, None, None)

    def p(self):
        return Profile("example", self.t.profiles)

    def path(self):
        return next(self.p().vacancies.glob("01 *.md"))

    def post(self, path, **body):
        return self.app.handle("POST", path, {}, {"profile": "example", **body})

    def card(self):
        return self.app.handle("GET", "/api/vacancy", {"profile": ["example"], "n": ["1"]}, {})

    def test_old_example_is_main_template(self):
        main = T.get(self.p())
        self.assertEqual((main["id"], main["name"], main["default"]), (1, "Основной", True))
        self.assertEqual(main["text"], read_text(self.p().letter_example).strip())

    def test_templates_and_own_history(self):
        tid = self.post("/api/letter/templates/save", name="Короткое для hh", text="Коротко: я подхожу.", default=True)["id"]
        self.assertEqual(tid, 2)
        self.post("/api/letter/templates/save", id=2, name="Короткое для hh", text="Коротко: я подхожу. Звоните.")
        self.assertEqual(T.default_id(self.p()), 2)
        hist2 = criteria_history.versions(self.p(), "letter:2")
        self.assertEqual({v["text"] for v in hist2}, {"Коротко: я подхожу.", "Коротко: я подхожу. Звоните."})
        self.assertFalse(any("Коротко" in v["text"] for v in criteria_history.versions(self.p(), "letter")))
        self.post("/api/letter/templates/save", name="Развёрнутое", text="Длинно.")
        with self.assertRaises(AssistantError):                                     # не больше трёх
            T.save(self.p(), None, "Четвёртое", "текст")
        with self.assertRaises(AssistantError):
            T.delete(self.p(), 1, self.app.trash)                                   # основной не удаляется

    def test_letter_by_template(self):
        tid = T.save(self.p(), None, "Ответ на вопросы", "ШАБЛОН-ОТВЕТ")
        prompts = []
        analysis.write_letter(self.p(), self.result, ask=lambda prompt, *a: prompts.append(prompt) or "Письмо.",
                              log=lambda *_: None, template=tid)
        self.assertIn("ШАБЛОН-ОТВЕТ", prompts[0])
        card = self.card()
        self.assertEqual((card["letters"][0]["template"], card["templates"]), ("Ответ на вопросы", 2))

    def test_delete_goes_to_trash(self):
        tid = T.save(self.p(), None, "Временный", "текст", default=True)
        res = self.post("/api/letter/templates/save", id=tid, do="delete")
        self.assertEqual([t["id"] for t in res["templates"]], [1])
        self.assertEqual(T.default_id(self.p()), 1)
        self.assertEqual(sorted(self.trashed), ["история образца письма 2", "образец письма 2.txt"])

    def test_sent_mark(self):
        analysis.write_letter(self.p(), self.result, ask=lambda *a: "Первое.", log=lambda *_: None)
        analysis.write_letter(self.p(), self.result, ask=lambda *a: "Второе.", log=lambda *_: None)
        old = self.card()["letters"][1]
        f = analysis.text_file(self.p(), self.result, "cover", old["key"])
        mtime = f.stat().st_mtime
        self.assertEqual(self.post("/api/letter/sent", n=1, kind="cover", key=old["key"], date="2026-10-27"), {"sent": "2026-10-27"})
        self.assertEqual(f.stat().st_mtime, mtime)                                   # место в списке версий не меняется
        card = self.card()
        self.assertEqual([v.get("sent") for v in card["letters"]], [None, "2026-10-27"])
        self.assertEqual(card["letters"][1]["text"], "Первое.")
        self.assertIn({"date": "2026-10-27", "time": "", "kind": "cover", "source": "sent"}, card["texts"])   # прошлая дата — без времени
        self.post("/api/letter/sent", n=1, kind="cover", key=old["key"], date="")       # снять отметку
        self.assertNotIn("sent", self.card()["letters"][1])
        with self.assertRaises(AssistantError):
            analysis.mark_sent(self.p(), self.result, "cover", "../../x")


if __name__ == "__main__":
    unittest.main()
