"""«Итоги недели»: числа недели, неделей раньше и за всё время, причины «нет», отсев по названию, вывод."""
import unittest
from datetime import date

from helpers import TempProfile

from vacancy_assistant import app as A, funnel, vacancies as V, weekly
from vacancy_assistant.textio import write_text

TODAY = date(2026, 10, 28)              # среда; прошлая неделя — 19–25.10, позапрошлая — 12–18.10
CRITERIA = "К1: ❌ — Санкт-Петербург" + "\n"


def setup(t, n, saved, analyzed, score, stage=None, when=None, bad=False):
    path = t.add_vacancy(n, f"ИТ-директор {n}", f"Компания {n}", saved=saved)
    write_text(t.profile.results / path.name,
               f"---\n---\n<!-- {{\"title\": \"ИТ-директор {n}\", \"company\": \"Компания {n}\", \"score\": {score}, "
               f"\"can\": 5, \"want\": 8, \"decision\": \"{'нет' if bad else 'да'}\", \"stage\": \"full\", \"date\": \"{analyzed}\"}} -->\n"
               f"# ИТ-директор {n}\n\nКритерии:\n" + (CRITERIA if bad else "К1: ✅ — Москва\n"))
    if stage:
        funnel.set_stage(t.profile.results / path.name, stage, when, "new")


class Weekly(unittest.TestCase):
    def test_bounds(self):
        self.assertEqual(weekly.bounds("last", TODAY), (date(2026, 10, 19), date(2026, 10, 25)))
        self.assertEqual(weekly.bounds("this", TODAY), (date(2026, 10, 26), date(2026, 11, 1)))
        self.assertEqual(weekly.bounds("last", date(2026, 10, 26))[0], date(2026, 10, 19))   # понедельник — итоги прошлой

    def test_counts(self):
        with TempProfile() as t:
            setup(t, 1, "20.10.2026", "2026-10-20", 8, "applied", date(2026, 10, 21))
            setup(t, 2, "21.10.2026", "2026-10-21", 9, "hr", date(2026, 10, 24))          # поздний этап — и отклик, и ответ
            setup(t, 3, "22.10.2026", "2026-10-22", 3, bad=True)
            setup(t, 4, "14.10.2026", "2026-10-14", 7, "applied", date(2026, 10, 15))     # позапрошлая неделя
            write_text(t.profile.seen, "1\t20.10.2026\tвзята\tИТ-директор\n2\t20.10.2026\tотсеяна\tМенеджер проектов\n"
                                       "3\t21.10.2026\tотсеяна\tДиректор по продажам\n4\t21.10.2026\tпо ссылке\tCIO\n")
            r = weekly.compute(t.profile, V.vacancy_rows(t.profile), "last", TODAY)
            w, p, a = r["week"], r["prev"], r["total"]
            self.assertEqual((w["added"], w["analyzed"], w["good"], w["applied"], w["answered"], w["interview"]), (3, 3, 2, 2, 1, 1))
            self.assertEqual((p["added"], p["applied"]), (1, 1))
            self.assertEqual((a["added"], a["applied"]), (4, 3))
            self.assertEqual((w["found"], w["title_ok"]), (3, 1))             # «по ссылке» — не поиск
            self.assertEqual(r["reasons"][0]["count"], 1)
            self.assertEqual(sum(d["count"] for d in r["title_drops"]), 2)
            self.assertTrue(all(d["reason"] for d in r["title_drops"]))
            self.assertIn("found", [m["key"] for m in r["metrics"]])
            self.assertIn("Добавлено: поиском hh и вручную", [m["label"] for m in r["metrics"]])
            self.assertEqual(r["conversions"][2], {"from": "applied", "to": "answered", "label": "Отклик → Ответ", "pct": 33,
                                                   "week": None})                       # дальше отклика по неделе — рано
            # неделя: разобраны 1, 2, 3; оценка 7+ у 1 и 2, отклик на обе
            self.assertEqual([c["week"] for c in r["conversions"][:2]],
                             [{"pct": 67, "n": 2, "of": 3}, {"pct": 100, "n": 2, "of": 2}])
            self.assertEqual(r["conversions"][1]["pct"], 100)                  # 7+ → отклик: 1, 2, 4 — все с откликом
            md = weekly.markdown(r)
            self.assertIn("# Итоги недели: 19.10.2026 — 25.10.2026", md)
            self.assertIn("| Откликов | 2 | 1 | 3 |", md)
            self.assertIn("| Отклик → Ответ | рано судить | 33% |", md)

    def test_salary_filter(self):
        """Фильтр hh.ru по зарплате — строкой в «Отсеяно при поиске»: число неизвестно, его отсекает hh."""
        from vacancy_assistant import setup as S
        from vacancy_assistant.profile import Profile
        with TempProfile() as t:
            self.assertIsNone(weekly.compute(t.profile, [], "last", TODAY)["salary_filter"])
            S.update_profile(t.profile, {"search_salary": "180000", "search_salary_only": True}, log=lambda *_: None)
            r = weekly.compute(Profile("example", t.profiles), [], "last", TODAY)
            self.assertEqual(r["salary_filter"]["text"], "Зарплата ниже 180 000 ₽ или зарплата не указана")
            self.assertIn("## Отсеяно при поиске", weekly.markdown(r))

    def test_no_search_hides_rows(self):
        with TempProfile() as t:
            r = weekly.compute(t.profile, V.vacancy_rows(t.profile), "last", TODAY)
            self.assertNotIn("found", [m["key"] for m in r["metrics"]])
            self.assertIn("не добавлено ни одной", r["advice"][0]["text"])

    def test_advice(self):
        zero = dict.fromkeys([k for k, _ in weekly.METRICS], 0)
        few = weekly.advice({**zero, "added": 5, "good": 4, "applied": 1}, zero, {**zero, "applied": 1}, [], [], 0)
        self.assertIn("4 вакансии с оценкой 7+, а откликов 1", few[0]["text"])
        silent = weekly.advice({**zero, "added": 5}, zero, {**zero, "applied": 20, "answered": 1}, [], [], 2)
        self.assertTrue(any("ответили на 1 из 20" in x["text"] for x in silent))
        self.assertTrue(any("2 отклика ждут" in x["text"] for x in silent))
        better = weekly.advice({**zero, "added": 5, "applied": 3}, {**zero, "applied": 1}, {**zero, "applied": 4}, [], [], 0)
        self.assertEqual(better[0]["kind"], "good")

    def test_title_reason(self):
        with TempProfile() as t:
            self.assertIsNone(t.profile.title_reason("ИТ-директор"))
            self.assertTrue(t.profile.title_reason("Менеджер по продажам"))

    def test_route(self):
        with TempProfile() as t:
            r = A.App(t.profiles, fetch_page=None, ask=None).handle("GET", "/api/weekly", {"profile": ["example"], "week": ["this"]}, {})
            self.assertEqual(r["which"], "this")
            self.assertIn("Итоги недели", r["markdown"])


if __name__ == "__main__":
    unittest.main()
