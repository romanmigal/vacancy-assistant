"""Набор вакансий для калибровки: свежие оценки, расхождения первыми, разные решения, предел по модели."""
import unittest
from datetime import date

from helpers import TempProfile

from vacancy_assistant import calibration as K, ratings


def vac(n, decision, diverge, date=""):
    return {"n": n, "decision": decision, "diverge": diverge, "date": date}


class Suggest(unittest.TestCase):
    def test_diverging_first_then_matching(self):
        rated = [vac(1, "да", False), vac(2, "да", True), vac(3, "да", False), vac(4, "да", True)]   # свежие первыми
        self.assertEqual(K.suggest(rated, 3), [2, 4, 1])

    def test_each_decision_represented(self):
        """По 2 на каждое решение, даже если расхождений больше, чем помещается."""
        rated = [vac(n, "да", True) for n in range(1, 7)] + [vac(7, "нет", False), vac(8, "нет", False),
                                                             vac(9, "нет", False), vac(10, "возможно", False)]
        self.assertEqual(K.suggest(rated, 6), [1, 2, 3, 7, 8, 10])

    def test_limit_and_small(self):
        rated = [vac(n, "да", n % 2 == 0) for n in range(1, 21)]
        self.assertEqual(len(K.suggest(rated, 12)), 12)
        self.assertEqual(K.suggest(rated[:3], 12), [2, 1, 3])
        self.assertEqual(K.suggest([], 8), [])

    def test_diverges(self):
        v = lambda yes, my, model: {"yes": yes, "model_yes": True, "score": my, "model_score": model}
        self.assertEqual([K.diverges(v(False, 3, 8)), K.diverges(v(True, 7, 8)), K.diverges(v(True, 6, 8)),
                          K.diverges(v(True, None, 8))], [True, False, True, False])

    def test_limit_by_model(self):
        with TempProfile() as t:
            self.assertEqual(K.limit(t.profile), K.LIMITS["two_stage"])


class Picked(unittest.TestCase):
    def test_recent_first_exclude_add(self):
        with TempProfile() as t:
            for n in range(1, 13):
                t.add_vacancy(n, "Начальник отдела ИТ" if n % 2 else "ИТ-директор")
                t.profile.results.mkdir(exist_ok=True)
            from helpers import fake_model
            from vacancy_assistant import analysis
            analysis.analyze(t.profile, log=lambda *_: None, ask=fake_model, summary=False)
            for n in range(1, 13):                       # чем больше номер, тем свежее; модель: нечётные — «нет»
                ratings.set_rating(t.profile, n, 7, 7, "нет" if n > 10 else "да", "", today=date(2026, 10, n))
            rated, unrated = K.vacancies(t.profile)
            self.assertEqual(([v["n"] for v in rated][:3], unrated), ([12, 11, 10], []))
            # 11 — «нет» как у модели, 12 — «нет», а модель «да»; расходятся ещё нечётные «да»
            self.assertEqual(K.picked(t.profile), [12, 9, 7, 5, 3, 1, 11, 10])
            K.choose(t.profile, 9, False)
            K.choose(t.profile, 2, True)                 # добавленная — сверх подобранных
            self.assertEqual(K.picked(t.profile), [12, 7, 5, 3, 1, 11, 10, 8, 2])
            K.reset(t.profile)
            self.assertEqual(K.picked(t.profile)[:2], [12, 9])


if __name__ == "__main__":
    unittest.main()
