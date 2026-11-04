"""Резюме под вакансию (#15): советы модели по резюме, вакансии и сильным сторонам из разбора,
версии — как у писем, правила о фактах в промпте; резюме профиля не меняется."""
import time
import unittest

from helpers import TempProfile, fake_model

from vacancy_assistant import analysis, app as A
from vacancy_assistant.textio import read_text


class ResumeFit(unittest.TestCase):
    def setUp(self):
        self.t = TempProfile().__enter__()
        self.t.add_vacancy(1, "Директор по ИТ")
        analysis.analyze(self.t.profile, log=lambda *_: None, ask=fake_model)
        self.result = next(self.t.profile.results.glob("01 *.md"))

    def tearDown(self):
        self.t.__exit__(None, None, None)

    def test_prompt_and_versions(self):
        p, prompts = self.t.profile, []
        resume = read_text(p.resume)
        ask = lambda prompt, *a: prompts.append(prompt) or fake_model(prompt)
        target = analysis.write_resume_fit(p, self.result, log=lambda *_: None, ask=ask)
        self.assertEqual(target.parent, p.resume_fits)
        for rule in ("Бери только факты из резюме", "Не переноси цифры между компаниями", "[уточните",
                     "Не приписывай навыков"):
            self.assertIn(rule, prompts[0])                                   # правила о фактах — как у писем
        self.assertIn("Директор по ИТ", prompts[0])                           # вакансия
        self.assertIn(resume.strip()[:40], prompts[0])                       # резюме
        text = read_text(target)
        self.assertIn("## Включить в резюме под вакансию", text)
        self.assertIn("## Можно не включать", text)
        self.assertIn('"prompt": "резюме под вакансию v2.txt"', text)
        self.assertNotIn("ДОПОЛНИТЕЛЬНО О СЕБЕ", prompts[0])               # без фактов — только по резюме
        self.assertIn("откуда: место в резюме", prompts[0])
        time.sleep(1.1)                                                       # версии различаются по секундам
        analysis.write_resume_fit(p, self.result, log=lambda *_: None, ask=fake_model)
        self.assertEqual(len(analysis.resume_fit_history(p, self.result.name)), 1)   # прежняя — в истории
        self.assertEqual(read_text(p.resume), resume)                        # резюме профиля не трогаем

    def test_extra_facts(self):
        """«Дополнительно о себе» (#52): факты — в промпте отдельным блоком, их можно включать с пометкой «добавьте в резюме»."""
        p, prompts = self.t.profile, []
        p.write_facts("Запустил ЦОД на 200 стоек в Пример Банке")
        analysis.write_resume_fit(p, self.result, log=lambda *_: None,
                                  ask=lambda prompt, *a: prompts.append(prompt) or fake_model(prompt))
        self.assertIn("=== ДОПОЛНИТЕЛЬНО О СЕБЕ", prompts[0])
        self.assertIn("- Запустил ЦОД на 200 стоек в Пример Банке", prompts[0])
        self.assertIn("добавьте в резюме", prompts[0])
        self.assertIn("Бери только факты из резюме и «Дополнительно о себе»", prompts[0])
        self.assertNotIn("{", prompts[0].split("=== РЕЗЮМЕ ===")[0])           # все поля шаблона заполнены

    def test_route_and_card(self):
        app = A.App(self.t.profiles, ask=fake_model)
        title, work = A.make_work(self.t.profile, "resume_fit", {"n": 1}, ask=fake_model)
        self.assertEqual(title, "Резюме под вакансию")
        work(lambda *_: None)
        d = app.handle("GET", "/api/vacancy", {"profile": ["example"], "n": ["1"]}, {})
        self.assertEqual(len(d["resume_fits"]), 1)
        self.assertTrue(d["resume_fits"][0]["current"])
        self.assertIn("## Обо мне", d["resume_fits"][0]["text"])
        self.assertNotIn("<!--", d["resume_fits"][0]["text"])
        self.t.add_vacancy(2, "Без разбора")
        with self.assertRaises(A.AssistantError):                            # без разбора — понятный отказ
            A.make_work(self.t.profile, "resume_fit", {"n": 2}, ask=fake_model)


if __name__ == "__main__":
    unittest.main()
