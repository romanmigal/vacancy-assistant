"""«Резюме против рынка» — расхождения со своей оценкой: выборка по дате своей оценки, расхождения (модель «нет»,
вы «да» — первыми) и их ❌ в общем списке, подсказка модели, правка резюме и «о себе» с пересчётом вакансий и «Вернуть как было»."""
import unittest
from datetime import date

from helpers import TempProfile, answer_for, fake_model

from vacancy_assistant import analysis, app as A, gaps, market, ratings
from vacancy_assistant.errors import AssistantError
from vacancy_assistant.textio import read_text

FACT = "Руководил внедрением ERP на 3 тыс. пользователей"
NO = """### Критерии:
К1: ✅ (Москва)
К2: ❌ (нужен опыт ERP)

### Требования:
1. Руководство командами от 50 человек — ✅ (банк)
2. Внедрение ERP — ❌ в резюме нет
3. Опыт в ритейле от 3 лет — ❌ в резюме нет

### Могу: 5/10 (два требования ❌)
Хочу: 4/10 (критерий К2 нарушен)
Оценка: 3/10

### Сильные стороны:
- Команда

### Пробелы:
1. Нет ERP

### Откликаться: нет"""


def model(prompt, *a):
    """Разбор: «отдела» — «нет» с ❌ (пока в резюме нет факта про ERP); иначе — как fake_model. Подсказка — текстом."""
    if "ПОДХОДЯТ МНЕ, А МОДЕЛЬ СКАЗАЛА" in prompt:
        return "### Внедрение ERP — в 2 вакансиях\n**Опора:** нет\n**Нарастить:** ERP"
    if "Начальник отдела" in prompt:
        return answer_for(prompt, 8, "да") if FACT in prompt else NO
    return fake_model(prompt)


class Gaps(unittest.TestCase):
    def setUp(self):
        self.t = TempProfile().__enter__()
        p = self.t.profile
        for n, title in ((1, "Начальник отдела ИТ"), (2, "Начальник отдела ИТ"), (3, "ИТ-директор"), (4, "ИТ-директор"), (5, "CTO")):
            self.t.add_vacancy(n, title)
        analysis.analyze(p, log=lambda *_: None, ask=model)
        ratings.set_rating(p, 1, 8, 8, "да", "моё", today=date(2026, 11, 2))         # модель «нет» — расхождение
        ratings.set_rating(p, 2, 6, 7, "возможно", "", today=date(2026, 11, 3))      # тоже, ниже по своей оценке
        ratings.set_rating(p, 3, 3, 3, "нет", "далеко", today=date(2026, 11, 3))     # модель «да», я «нет»
        ratings.set_rating(p, 4, 8, 8, "да", "", today=date(2026, 11, 3))            # совпало
        ratings.set_rating(p, 5, 8, 8, "да", "", today=date(2026, 9, 1))             # раньше даты — не берём
        self.rows = lambda: A.vacancy_rows(self.t.profile)

    def tearDown(self):
        self.t.__exit__(None, None, None)

    def test_report(self):
        full = market.report(self.t.profile, self.rows(), "2026-11-01")
        rep = full["own"]
        self.assertEqual((rep["rated"], rep["same"], [v["n"] for v in rep["under"]], [v["n"] for v in rep["over"]]),
                         (4, 1, [1, 2], [3]))
        self.assertEqual(rep["under"][0]["failed"], ["Внедрение ERP", "Опыт в ритейле от 3 лет"])
        self.assertEqual(rep["under"][0]["criteria"][0]["k"], "2")
        self.assertEqual((rep["under"][0]["mine"]["decision"], rep["under"][0]["model"]["score"]), ("да", 3))
        self.assertEqual(full["vacancies"], 0)                                   # откликов нет — а ❌ расхождений в списке
        self.assertEqual(full["gaps"][0]["count"], 2)                            # «Внедрение ERP» — в обеих
        self.assertEqual(gaps.discrepancies(self.t.profile, self.rows(), "2026-11-03")["rated"], 3)

    def test_route_and_advice(self):
        app = A.App(self.t.profiles, ask=model)
        rep = app.handle("POST", "/api/market", {}, {"profile": "example", "since": "2026-11-01"})
        self.assertEqual(len(rep["own"]["under"]), 2)
        prompts = []
        ask = lambda prompt, *a: prompts.append(prompt) or model(prompt)
        _, work = A.make_work(self.t.profile, "market_advice", {"since": "2026-11-01"}, ask=ask)
        work(lambda *_: None)
        self.assertIn("Внедрение ERP", prompts[0])
        self.assertIn("Моя причина: моё", prompts[0])
        self.assertNotIn("CTO", prompts[0])                                       # оценка раньше даты
        advice = market.report(self.t.profile, self.rows(), "2026-11-01")["advice"]
        self.assertIn("Нарастить", advice["text"])
        self.assertEqual((advice["under"], advice["since"]), (2, "2026-11-01"))

    def test_recheck_and_undo(self):
        p = self.t.profile
        result = next(p.results.glob("01*.md"))
        before = read_text(result)
        _, work = A.make_work(p, "market_recheck", {"ns": [1, 2], "facts": f"- {FACT}\n"}, ask=model)
        work(lambda *_: None)
        rc = market.report(p, self.rows(), "2026-11-01")["recheck"]
        self.assertEqual(rc["changed"], ["facts"])
        self.assertEqual([(i["n"], i["before"]["decision"], i["after"]["decision"], i["before"]["failed"], i["after"]["failed"])
                          for i in rc["items"]], [(1, "нет", "да", 2, 0), (2, "нет", "да", 2, 0)])
        self.assertEqual(p.read_facts(), [FACT])
        self.assertEqual(gaps.discrepancies(p, self.rows(), "2026-11-01")["under"], [])  # расхождений больше нет
        gaps.undo(p)
        self.assertEqual((p.read_facts(), read_text(result)), ([], before))
        with self.assertRaises(AssistantError):
            gaps.undo(p)
        with self.assertRaises(AssistantError):
            A.make_work(p, "market_recheck", {"ns": []})
        self.assertIn("market_recheck", A.NEEDS_MODEL)


if __name__ == "__main__":
    unittest.main()
