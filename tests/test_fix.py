"""Правка критериев по одной вакансии: «оценка должна быть выше / ниже» — предложение правки, проверка на
вакансии и на оценённых вакансиях, применение; рабочие критерии не меняются до «Применить»."""
import unittest
from unittest import mock

from helpers import TempProfile, answer_for, fake_model

from vacancy_assistant import analysis, app as A, criteria_history, fix, ratings, vacancies as V, work as W
from vacancy_assistant.errors import AssistantError
from vacancy_assistant.textio import read_text, write_text

RULE = "Руководитель направления с разработкой — не нарушение"


def model(company=""):
    """Модель: на просьбу о правке ослабляет К3; разбор с новыми критериями — 8 и «да», иначе как fake_model."""
    def ask(prompt, *a):
        if "Предложи минимальную правку" in prompt:
            criteria = prompt.split("=== ТЕКУЩИЕ КРИТЕРИИ ===\n", 1)[1].split("\n\n=== ВАКАНСИЯ", 1)[0]
            new = criteria.replace("тимлид — нарушение.", f"тимлид — нарушение. {RULE}{company}.")
            return f"Что меняю: ослабил К3 для руководителей направлений.\n=== КРИТЕРИИ ===\n{new}\n=== КОНЕЦ ==="
        if RULE in prompt:
            return answer_for(prompt, 8, "да")
        return fake_model(prompt)
    return ask


ANSWER = """### Критерии:
К1: ✅ (Москва)
К2: ❓ (зарплата не указана)
К3: ❌ (роль — лидер стрима, не руководитель всех ИТ)

### Требования:
1. Руководство командами от 50 человек — ✅ (Банк «Пример»)
2. Внедрение ИИ в разработку — ❌ в резюме нет

### Могу: 8/10 (одно требование ❌)
Хочу: 3/10 (жёсткий критерий К3 нарушен)
Оценка: 4/10

### Сильные стороны:
- Построение ИТ с нуля

### Пробелы:
1. Нет опыта внедрения ИИ

### Откликаться: нет"""


class Fix(unittest.TestCase):
    def setUp(self):
        self.t = TempProfile().__enter__()
        self.t.add_vacancy(1, "Начальник отдела ИТ")                # fake_model: 3 и «нет»
        self.t.add_vacancy(2, "ИТ-директор")                       # 8 и «да»
        analysis.analyze(self.t.profile, log=lambda *_: None, ask=fake_model)
        self.criteria = self.t.profile.read_criteria()

    def tearDown(self):
        self.t.__exit__(None, None, None)

    def suggest(self, ask=None, **extra):
        data = {"n": 1, "direction": "up", "reason": "направление с разработкой мне интересно",
                "marks": ["К3: руководитель направления"], **extra}
        _, work = W.make_work(self.t.profile, "fix_suggest", data, ask=ask or model())
        work(lambda *_: None)
        return fix.read_state(self.t.profile, 1)

    def test_factors(self):
        f = fix.factors(ANSWER)
        self.assertEqual([(c["k"], c["mark"]) for c in f["criteria"]], [("1", "✅"), ("2", "❓"), ("3", "❌")])
        self.assertEqual([r["ok"] for r in f["requirements"]], [True, False])
        self.assertEqual((f["gaps"], f["strengths"]), (["Нет опыта внедрения ИИ"], ["Построение ИТ с нуля"]))
        self.assertIn("К3 нарушен", f["want"])

    def test_keep_unchanged(self):
        old = "К1. Локация: Москва или удалённо. Переезд в другой город — нет.\nК2. Уровень: руководитель всего ИТ."
        new = "К1. Локация: Москва или удалённо. Перевод в другой город — нет.\nК2. Уровень: руководитель всего ИТ или крупного направления разработки."
        self.assertEqual(fix.keep_unchanged(old, new),
                         "К1. Локация: Москва или удалённо. Переезд в другой город — нет.\n"
                         "К2. Уровень: руководитель всего ИТ или крупного направления разработки.")

    def test_suggest_checks_vacancy_without_changing_criteria(self):
        st = self.suggest()
        self.assertIsNone(st["problem"])
        self.assertEqual((st["before"]["score"], st["after"]["score"], st["after"]["decision"]), (3, 8, "да"))
        self.assertTrue(st["achieved"])
        self.assertTrue(any(RULE in l for l in st["diff"] if l.startswith("+")))
        self.assertEqual(self.t.profile.read_criteria(), self.criteria)          # рабочие критерии — те же
        again = self.suggest(history=st["history"])                            # «другой вариант» — помнит прежние
        self.assertEqual(len(again["history"]), 2)

    def test_company_name_rejected(self):
        st = self.suggest(ask=model(" (как в ООО Пример)"))
        self.assertIn("ООО Пример", st["problem"])
        self.assertIsNone(st["after"])
        with self.assertRaises(AssistantError):
            fix.apply(self.t.profile, 1)

    def test_manual_text(self):
        manual = self.criteria.replace("тимлид — нарушение.", f"тимлид — нарушение. {RULE}.")
        st = self.suggest(ask=lambda *a: self.fail("правку не просим") if "Предложи" in a[0] else model()(*a), manual=manual)
        self.assertEqual((st["what"], st["after"]["score"]), ("ручная правка", 8))

    def test_reference_and_apply(self):
        p = self.t.profile
        ratings.set_rating(p, 1, 7, 7, "да", "направление с разработкой")
        ratings.set_rating(p, 2, 8, 8, "да", "")
        self.suggest()
        _, work = W.make_work(p, "fix_check", {"n": 1}, ask=model())
        work(lambda *_: None)
        ref = fix.read_state(p, 1)["reference"]
        self.assertEqual((ref["before"]["решение совпало"], ref["after"]["решение совпало"]), (1, 2))
        self.assertEqual([(c["n"], c["before"], c["after"]) for c in ref["changed"]], [(1, False, True)])
        fix.apply(p, 1)
        self.assertIn(RULE, p.read_criteria())
        self.assertFalse(fix.state_path(p).exists())
        vs = criteria_history.versions(p)
        self.assertTrue(vs[0]["current"] and vs[0]["source"].startswith("правка по вакансии 01"))
        self.assertEqual(vs[0]["measure"]["совпало"], 2)
        self.assertTrue(any(v["source"] == "до правки по вакансии 01" for v in vs))
        self.assertTrue(V.vacancy_rows(p)[0]["criteria_changed"])                  # предложат пересчитать оценки

    def test_stale_after_criteria_change(self):
        self.suggest()
        write_text(self.t.profile.criteria_file, self.criteria + "\n+ банки;\n")
        self.assertIsNone(fix.read_state(self.t.profile, 1))
        with self.assertRaises(AssistantError):
            fix.apply(self.t.profile, 1)

    def test_check_needs_ratings(self):
        self.suggest()
        _, work = W.make_work(self.t.profile, "fix_check", {"n": 1}, ask=model())
        with self.assertRaises(AssistantError) as e:
            work(lambda *_: None)
        self.assertIn("Нет оценённых", str(e.exception))

    def test_route(self):
        app = A.App(self.t.profiles, ask=fake_model)
        v = app.handle("GET", "/api/fix", {"profile": ["example"], "n": ["1"]}, {})
        self.assertEqual((v["model"]["score"], v["model"]["decision"], v["reference"], v["state"]), (3, "нет", 0, None))
        self.assertEqual(v["factors"]["criteria"][0]["k"], "1")
        with mock.patch.object(W.setup, "ollama_models", return_value=["gemma4:12b"]):   # Ollama «запущена»
            self.assertIn("Правка критериев", W.make_work(self.t.profile, "fix_suggest", {"n": 1, "direction": "up"})[0])
            with self.assertRaises(AssistantError):
                W.make_work(self.t.profile, "fix_suggest", {"n": 1})
        self.assertIn("fix_suggest", W.SINGLE)
        self.assertEqual(read_text(self.t.profile.criteria_file).strip(), self.criteria.strip())


class Recheck(unittest.TestCase):
    """Правка своими руками: критерии, резюме, «о себе» → пересчёт вакансии → «Вернуть как было»."""

    def setUp(self):
        self.t = TempProfile().__enter__()
        self.t.add_vacancy(1, "Начальник отдела ИТ")                # fake_model: 3 и «нет»
        analysis.analyze(self.t.profile, log=lambda *_: None, ask=fake_model)
        p = self.t.profile
        self.file = next(p.results.glob("01*.md"))
        self.criteria, self.resume, self.result = p.read_criteria(), p.read_resume(), read_text(self.file)

    def tearDown(self):
        self.t.__exit__(None, None, None)

    def recheck(self, **data):
        _, work = W.make_work(self.t.profile, "fix_recheck", {"n": 1, **data}, ask=model())
        work(lambda *_: None)
        return fix.read_recheck(self.t.profile, 1)

    def test_criteria_and_undo(self):
        p = self.t.profile
        new = self.criteria.replace("тимлид — нарушение.", f"тимлид — нарушение. {RULE}.")
        st = self.recheck(criteria=new, facts="руководил разработкой\nвнедрял ИИ")
        self.assertEqual(st["changed"], ["criteria", "facts"])
        self.assertEqual(((st["before"]["score"], st["before"]["decision"]), (st["after"]["score"], st["after"]["decision"])),
                         ((3, "нет"), (8, "да")))
        self.assertIn(RULE, p.read_criteria())
        self.assertEqual(p.read_facts(), ["руководил разработкой", "внедрял ИИ"])
        self.assertTrue(any(RULE in v["text"] for v in criteria_history.versions(p)))
        self.assertEqual(A.App(self.t.profiles).handle("GET", "/api/fix", {"profile": ["example"], "n": ["1"]}, {})["recheck"]["n"], 1)
        fix.undo(p, 1)
        self.assertEqual((p.read_criteria().strip(), p.read_facts()), (self.criteria.strip(), []))
        self.assertEqual(read_text(self.file), self.result)
        self.assertIsNone(fix.read_recheck(p, 1))

    def test_nothing_changed(self):
        st = self.recheck(criteria=self.criteria, resume=self.resume)
        self.assertEqual(st["changed"], [])                       # тексты те же — просто пересчёт
        with self.assertRaises(AssistantError):
            self.recheck(criteria="  ")

    def test_route(self):
        self.assertIn("fix_recheck", W.SINGLE)
        self.assertIn("fix_recheck", W.NEEDS_MODEL)
        with self.assertRaises(AssistantError):
            fix.undo(self.t.profile, 1)


if __name__ == "__main__":
    unittest.main()
