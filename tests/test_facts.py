"""«Дополнительно о себе» (#51): факты вне резюме — в промптах разбора и оценки, в отпечатке оценки, в мастере."""
import unittest

from helpers import TempProfile, fake_model

from vacancy_assistant import analysis, app as A, setup
from vacancy_assistant.profile import FACTS_HEAD, Profile, parse_facts
from vacancy_assistant.textio import read_text, write_text

ANSWERS = {"name": "Мария Иванова", "field": "финансы", "resume": "# Резюме\n\nГлавный бухгалтер.",
           "titles": "Главный бухгалтер", "city": "Москва", "office": True, "hybrid": True, "remote": True}


class Facts(unittest.TestCase):
    def setUp(self):
        self.t = TempProfile().__enter__()
        self.t.add_vacancy(1, "ИТ-директор")
        self.app = A.App(self.t.profiles, fetch_page=lambda url: "", ask=fake_model,
                         check=lambda: {"ollama": True, "model_ok": True})

    def tearDown(self):
        self.t.__exit__(None, None, None)

    def p(self):
        return Profile("example", self.t.profiles)

    def test_empty_changes_nothing(self):
        p = self.p()
        before = (p.analysis_prompt("резюме", "вакансия"), p.scoring_prompt("резюме", "вакансия"), p.criteria_hash())
        write_text(p.facts_file, "\n# Заголовок\n\n")                  # пустой файл — как без него
        p = self.p()
        self.assertEqual((p.analysis_prompt("резюме", "вакансия"), p.scoring_prompt("резюме", "вакансия"), p.criteria_hash()), before)
        self.assertNotIn(FACTS_HEAD, before[0])

    def test_facts_in_prompts_and_hash(self):
        p = self.p()
        old = p.criteria_hash()
        write_text(p.facts_file, "- Использую ИИ в своих проектах\n* Английский B2\n\n1. Волонтёр\n")
        p = self.p()
        self.assertEqual(p.read_facts(), ["Использую ИИ в своих проектах", "Английский B2", "Волонтёр"])
        for prompt in (p.analysis_prompt("Моё резюме", "ТЕКСТ ВАКАНСИИ"), p.scoring_prompt("Моё резюме", "ТЕКСТ ВАКАНСИИ")):
            block = f"Моё резюме\n\n{FACTS_HEAD}\n- Использую ИИ в своих проектах\n- Английский B2\n- Волонтёр"
            self.assertIn(block, prompt)
            self.assertLess(prompt.index(FACTS_HEAD), prompt.index("ТЕКСТ ВАКАНСИИ"))
        self.assertNotEqual(p.criteria_hash(), old)

    def test_list_with_dashes(self):
        """С «-» факт — от маркера до маркера: перенос строки внутри факта не делит его на два."""
        p = self.p()
        p.write_facts("- Руководил ИТ в банке,\n  внедрил ДБО для 2 млн клиентов\n-\n- Английский B2\n")
        self.assertEqual(p.read_facts(), ["Руководил ИТ в банке, внедрил ДБО для 2 млн клиентов", "Английский B2"])
        self.assertEqual(setup.answers_from_profile(p)["facts"],
                         "- Руководил ИТ в банке, внедрил ДБО для 2 млн клиентов\n- Английский B2\n")
        self.assertEqual(parse_facts("без маркеров\nфакт на строку"), ["без маркеров", "факт на строку"])

    def test_changed_facts_mark_scores(self):
        analysis.analyze(self.p(), log=lambda *_: None, ask=fake_model)
        state = lambda: self.app.handle("GET", "/api/state", {"profile": ["example"]}, {})
        self.assertFalse(state()["rows"][0]["criteria_changed"])
        res = self.app.handle("POST", "/api/profile/update", {}, {"profile": "example", "answers": {"facts": "Пет-проект на Python\n\n"}})
        self.assertIn("дополнительно о себе", res["changed"])
        self.assertEqual(read_text(self.p().facts_file), "- Пет-проект на Python\n")
        self.assertTrue(state()["rows"][0]["criteria_changed"])               # кнопка «Пересчитать оценки»
        self.assertEqual(self.app.handle("GET", "/api/profile/answers", {"profile": ["example"]}, {})["facts"], "- Пет-проект на Python\n")
        res = self.app.handle("POST", "/api/profile/update", {}, {"profile": "example", "answers": {"facts": ""}})
        self.assertFalse(state()["rows"][0]["criteria_changed"])              # убрали — снова как при оценке

    def test_changed_resume_marks_scores(self):
        """Поменяли резюме — прежние оценки устарели: кнопка «Пересчитать оценки»; старые разборы без отпечатка
        резюме — по истории разборов, а если и её нет — не отмечаем."""
        import json
        from vacancy_assistant import funnel
        from vacancy_assistant.files import read_meta
        analysis.analyze(self.p(), log=lambda *_: None, ask=fake_model)
        state = lambda: self.app.handle("GET", "/api/state", {"profile": ["example"]}, {})
        self.assertFalse(state()["rows"][0]["criteria_changed"])
        resume = read_text(self.p().resume)
        res = self.app.handle("POST", "/api/profile/update", {}, {"profile": "example", "answers": {"resume": resume + "\nНовый опыт: ИИ."}})
        self.assertIn("резюме", res["changed"])
        self.assertTrue(state()["rows"][0]["criteria_changed"])
        # Разбор прежней версии: в паспорте нет отпечатка резюме — берём его из истории разборов
        result = next(self.p().results.glob("01 *.md"))
        meta = read_meta(result)
        text = read_text(result).replace(json.dumps(meta, ensure_ascii=False),
                                         json.dumps({k: v for k, v in meta.items() if k != "resume_hash"}, ensure_ascii=False))
        write_text(result, text)
        self.assertNotIn("resume_hash", read_meta(result))
        self.assertTrue(state()["rows"][0]["criteria_changed"])
        (self.p().dir / funnel.ANALYSES_FILE).unlink()                       # и истории нет — неизвестно, не отмечаем
        self.assertFalse(state()["rows"][0]["criteria_changed"])

    def test_wizard_creates_file(self):
        name = setup.create_profile({**ANSWERS, "facts": "Языки: английский C1"}, self.t.profiles, log=lambda *_: None)
        self.assertEqual(Profile(name, self.t.profiles).read_facts(), ["Языки: английский C1"])
        name = setup.create_profile({**ANSWERS, "name": "Анна Петрова"}, self.t.profiles, log=lambda *_: None)
        self.assertFalse(Profile(name, self.t.profiles).facts_file.exists())


if __name__ == "__main__":
    unittest.main()
