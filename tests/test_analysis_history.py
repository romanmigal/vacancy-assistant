"""История разборов: каждый разбор — запись с решением и тремя оценками; видно, что поменялось."""
import unittest

from helpers import TempProfile, fake_model

from vacancy_assistant import analysis, app as A, funnel
from vacancy_assistant.profile import Profile
from vacancy_assistant.textio import read_text, write_text


class AnalysisHistory(unittest.TestCase):
    def setUp(self):
        self.t = TempProfile().__enter__()
        self.t.add_vacancy(1, "ИТ-директор")
        self.app = A.App(self.t.profiles, fetch_page=lambda url: "", ask=fake_model,
                         check=lambda: {"ollama": True, "model_ok": True})

    def tearDown(self):
        self.t.__exit__(None, None, None)

    def p(self):
        return Profile("example", self.t.profiles)

    def path(self):
        return next(self.p().vacancies.glob("01 *.md"))

    def analyses(self):
        return self.app.handle("GET", "/api/vacancy", {"profile": ["example"], "n": ["1"]}, {})["analyses"]

    def test_records_and_changes(self):
        analysis.full_analysis(self.p(), self.path(), ask=fake_model, log=lambda *_: None)
        analysis.full_analysis(self.p(), self.path(), ask=fake_model, log=lambda *_: None)   # заново, без правок
        p = self.p()
        write_text(p.resume, read_text(p.resume) + "\nЕщё опыт.\n")
        write_text(p.facts_file, "- Пет-проект\n")
        analysis.full_analysis(self.p(), self.path(), ask=fake_model, log=lambda *_: None)
        items = self.analyses()
        self.assertEqual(len(items), 3)
        self.assertEqual({k: items[0][k] for k in ("decision", "score", "can", "want", "stage")},
                         {"decision": "да", "score": 8, "can": 7, "want": 8, "stage": "full"})
        self.assertTrue(items[0]["time"])
        self.assertIsNone(items[0]["changed"])                                  # первый — сравнивать не с чем
        self.assertEqual(items[1]["changed"], [])                               # разница — только разброс модели
        self.assertEqual(items[2]["changed"], ["резюме", "о себе"])

    def test_short_and_full_in_one_run(self):
        self.assertTrue(self.p().two_stage)                                     # профиль-пример — в две ступени
        analysis.analyze(self.p(), log=lambda *_: None, ask=fake_model)
        self.assertEqual([e["stage"] for e in self.analyses()], ["short", "full"])   # «да» — короткая, потом полный


if __name__ == "__main__":
    unittest.main()
