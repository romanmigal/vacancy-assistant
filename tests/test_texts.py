"""Правка писем и резюме под вакансию, свои письма: каждое сохранение — новая версия, прежняя — в истории."""
import unittest

from helpers import TempProfile, fake_model

from vacancy_assistant import analysis, app as A
from vacancy_assistant.errors import AssistantError
from vacancy_assistant.files import REFERRER_PROP, read_meta, set_prop
from vacancy_assistant.profile import Profile


class Texts(unittest.TestCase):
    def setUp(self):
        self.t = TempProfile().__enter__()
        self.t.add_vacancy(1, "ИТ-директор")
        self.app = A.App(self.t.profiles, fetch_page=lambda url: "", ask=fake_model,
                         check=lambda: {"ollama": True, "model_ok": True})
        analysis.full_analysis(self.p(), self.path(), ask=fake_model, log=lambda *_: None)
        self.result = self.p().results / self.path().name

    def tearDown(self):
        self.t.__exit__(None, None, None)

    def p(self):
        return Profile("example", self.t.profiles)

    def path(self):
        return next(self.p().vacancies.glob("01 *.md"))

    def card(self):
        return self.app.handle("GET", "/api/vacancy", {"profile": ["example"], "n": ["1"]}, {})

    def save(self, kind, text, source):
        return self.app.handle("POST", "/api/text/save", {},
                               {"profile": "example", "n": 1, "kind": kind, "text": text, "source": source})

    def test_edit_keeps_model_version(self):
        analysis.write_letter(self.p(), self.result, ask=lambda *a: "Письмо модели.", log=lambda *_: None)
        self.assertEqual(self.save("cover", "Письмо модели, поправленное.\n\nС уважением", "edit"), {"ok": True})
        letters = self.card()["letters"]
        self.assertEqual([(v["text"].splitlines()[0], v.get("source"), v["current"]) for v in letters],
                         [("Письмо модели, поправленное.", "edit", True), ("Письмо модели.", None, False)])
        self.assertEqual([(e["kind"], e["source"]) for e in self.card()["texts"]], [("cover", "edit")])

    def test_two_own_referrer_letters(self):
        set_prop(self.result, REFERRER_PROP, "Иван Петров")
        self.save("referrer", "Привет! Передашь резюме?", "own")
        self.save("referrer", "Спасибо, что передал.", "own")
        letters = self.card()["ref_letters"]
        self.assertEqual([v["text"] for v in letters], ["Спасибо, что передал.", "Привет! Передашь резюме?"])
        self.assertEqual({(v["source"], v["to"]) for v in letters}, {("own", "Иван Петров")})

    def test_resume_fit(self):
        self.save("resume", "Обо мне: руководитель ИТ…", "own")
        fits = self.card()["resume_fits"]
        self.assertEqual((fits[0]["text"], fits[0]["source"]), ("Обо мне: руководитель ИТ…", "own"))
        self.assertEqual(read_meta(self.p().resume_fits / self.path().name)["source"], "own")

    def test_empty_and_unknown_rejected(self):
        with self.assertRaises(AssistantError):
            analysis.save_text(self.p(), self.result, "cover", "  \n ", "own")
        with self.assertRaises(AssistantError):
            analysis.save_text(self.p(), self.result, "interview", "текст", "own")
        self.assertFalse((self.p().letters / self.path().name).exists())


if __name__ == "__main__":
    unittest.main()
