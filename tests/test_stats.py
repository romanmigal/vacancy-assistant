"""Раздел «Статистика»: подсчёт по дням, неделям и месяцам, средние без будущих дней, воронка, скорость."""
import unittest
from datetime import date

from helpers import TempProfile, fake_model

from vacancy_assistant import analysis, app as A, funnel, stats

TODAY = date(2026, 10, 28)                          # среда


def row(n, added, analyzed="", score=None, status="new", stages=(), statuses=(), source="HH", letter=False):
    return {"n": n, "cover_sent": letter, "title": f"Вакансия {n}", "company": "ООО Пример", "source": source, "added_key": added,
            "analyzed": bool(analyzed), "analyzed_on": analyzed, "score": score, "status": status, "flag": False,
            "funnel": {"stage": stages[-1][0] if stages else "",
                       "history": [{"stage": s, "date": d, "time": ""} for s, d in stages],
                       "statuses": [{"status": s, "date": d, "time": ""} for s, d in statuses]}}


ROWS = [
    row(1, "2026-10-26", "2026-10-26", 8, "yes", [("applied", "2026-10-27"), ("answered", "2026-10-28")],
        [("yes", "2026-10-27")], letter=True),
    row(2, "2026-10-19", "2026-10-20", 5, "no", statuses=[("no", "2026-10-20")]),
    row(3, "2026-10-12", "2026-10-12", 9, "yes", [("applied", "2026-10-13")], [("yes", "2026-10-13")], source="Хабр Карьера"),
    row(4, "2026-09-01", "2026-09-01", 7, "interview", [("applied", "2026-09-02"), ("hr", "2026-09-10")]),
    row(5, "2026-10-27", status="no"),
]


class Stats(unittest.TestCase):
    def test_weeks(self):
        s = stats.compute(ROWS, "week", TODAY, [("new", "Не обработано"), ("yes", "Интересно"), ("no", "Не подходит"),
                                                 ("interview", "Интервью")])
        self.assertEqual(len(s["series"]), 12)
        last, prev = s["series"][-1], s["series"][-2]
        self.assertEqual((last["start"], last["end"], last["partial"]), ("2026-10-26", "2026-11-01", True))
        self.assertEqual((last["added"], last["analyzed"], last["applied"], last["answered"]), (2, 1, 1, 1))
        self.assertEqual(prev["added"], 1)
        t = s["totals"]
        self.assertEqual(t["added"]["total"], 5)                  # 12 недель — с 10 августа
        # среднее: 11 полных недель + 3 дня из 7 текущей — текущая неполная не занижает
        self.assertEqual(t["added"]["avg"], round(5 / (11 + 3 / 7), 1))
        self.assertEqual(t["applied"]["total"], 3)
        self.assertEqual([f["count"] for f in s["funnel"]], [5, 4, 3, 3, 2, 1, 0])
        self.assertEqual(s["waiting"], [{"n": 3, "title": "Вакансия 3", "company": "ООО Пример", "applied": "2026-10-13",
                                         "days": 15}])
        self.assertEqual(s["speed"]["to_answer"], {"days": 4.5, "count": 2})   # 1 день и 8 дней (до интервью)
        self.assertEqual(s["speed"]["to_interview"], {"days": 8.0, "count": 1})
        self.assertEqual({x["source"]: x["applied"] for x in s["sources"]}, {"HH": 2, "Хабр Карьера": 1})
        self.assertEqual({x["label"]: x["count"] for x in s["statuses"]},
                         {"Не обработано": 0, "Интересно": 2, "Не подходит": 2, "Интервью": 1})   # и пустые статусы
        self.assertEqual(s["score"], {"avg": 7.2, "good": 3, "count": 4})
        self.assertEqual(s["letters"], [{"letter": True, "applied": 1, "answered": 1, "rejected": 0, "interview": 0},
                                        {"letter": False, "applied": 2, "answered": 1, "rejected": 0, "interview": 1}])
        old = stats.compute(ROWS, "week", date(2027, 1, 20))     # прошлые 12 недель — для сравнения
        self.assertEqual((old["totals"]["added"]["total"], old["totals"]["added"]["prev"]), (0, 5))

    def test_statuses_open_closed_flagged(self):
        rows = [dict(ROWS[0], flag=True), dict(ROWS[2], actual={"closed": True}), *ROWS[1:2], *ROWS[3:]]
        st = {x["key"]: x for x in stats.compute(rows, "week", TODAY, [("new", "Не обработано"), ("yes", "Интересно")])["statuses"]}
        self.assertEqual({k: st["yes"][k] for k in ("count", "closed", "flagged")}, {"count": 2, "closed": 1, "flagged": 1})
        self.assertEqual(st["new"]["count"], 0)

    def test_scores_model_and_mine(self):
        rows = [dict(ROWS[0], my_score=6), dict(ROWS[1], my_score=5), dict(ROWS[2], my_score=10), *ROWS[3:]]
        sc = stats.compute(rows, "week", TODAY)["scores"]
        self.assertEqual(sc["model"], [0, 0, 0, 0, 1, 0, 1, 1, 1, 0])        # 8, 5, 9, 7; у пятой оценки нет
        self.assertEqual(sc["mine"], [0, 0, 0, 0, 1, 1, 0, 0, 0, 1])
        self.assertEqual((sc["both"], sc["higher"], sc["lower"], sc["diff_avg"]), (3, 1, 1, 1.0))
        self.assertEqual({d: n for d, n in zip(range(-9, 10), sc["diffs"]) if n}, {-1: 1, 0: 1, 2: 1})   # 9↔10, 5↔5, 8↔6
        self.assertEqual((sc["model_avg"], sc["mine_avg"]), (7.2, 7.0))

    def test_answers_model_and_mine(self):
        rows = [dict(ROWS[0], decision="да", my_decision="да"), dict(ROWS[1], decision="нет", my_decision="возможно"),
                dict(ROWS[2], decision="да, но с оговорками"), dict(ROWS[3], decision="нет", my_decision="нет"),
                dict(ROWS[4], decision="да", my_decision="нет")]          # у пятой нет оценки модели — её ответ не в счёт
        sc = stats.compute(rows, "week", TODAY)["scores"]
        self.assertEqual((sc["ans_model"], sc["ans_mine"], sc["ans_both"]), ([1, 1, 2], [1, 1, 2], 3))
        self.assertEqual(sc["ans_matrix"], [[1, 0, 0], [0, 0, 0], [0, 1, 1]])   # строка — модель, столбец — вы

    def test_engines(self):
        rows = [dict(ROWS[0], model="gemma4:12b", stage="short", decision="да", my_score=8),
                dict(ROWS[1], model="GigaChat-2-Pro", decision="нет", my_score=7),
                dict(ROWS[2], model="GigaChat-2-Pro", decision="да, но с оговорками"), ROWS[3], ROWS[4]]
        e = {x["key"]: x for x in stats.compute(rows, "week", TODAY)["engines"]}
        # разбор без названия модели — старый, до облака: локальная; не разобранная — «без оценки»
        self.assertEqual({k: e[k]["count"] for k in e}, {"local": 2, "cloud": 2, "none": 1})
        self.assertEqual((e["local"]["names"], e["local"]["short"], e["local"]["yes"], e["local"]["same"]), (["gemma4:12b"], 1, 1, 1))
        self.assertEqual((e["cloud"]["names"], e["cloud"]["full"], e["cloud"]["maybe"], e["cloud"]["both"], e["cloud"]["near"]),
                         (["GigaChat-2-Pro"], 2, 1, 1, 0))

    def test_funnel_by_kind(self):
        rows = [dict(ROWS[0], agency=True), *ROWS[1:4], dict(ROWS[4], company="")]
        f = {x["label"]: x["by_kind"] for x in stats.compute(rows, "week", TODAY, [])["funnel"]}
        self.assertEqual(f["Добавлено"], {"employer": 3, "agency": 1, "hidden": 1})
        self.assertEqual(f["Ответили"], {"employer": 1, "agency": 1, "hidden": 0})

    def test_later_stage_implies_apply(self):
        """Сразу «Интервью с HR» без «Откликнулся» — это и отклик, и ответ; в скорость такая вакансия не идёт."""
        s = stats.compute([row(1, "2026-10-20", "2026-10-20", 8, "interview", [("hr", "2026-10-27")])], "week", TODAY)
        self.assertEqual([s["totals"][k]["total"] for k in ("applied", "answered", "interview")], [1, 1, 1])
        self.assertEqual(s["speed"]["to_answer"], {"days": None, "count": 0})
        r = stats.compute([row(2, "2026-10-20", "2026-10-20", 5, "no", [("applied", "2026-10-21"), ("rejected", "2026-10-27")])],
                          "week", TODAY)
        self.assertEqual([r["totals"][k]["total"] for k in ("applied", "answered", "rejected", "interview")], [1, 1, 1, 0])

    def test_days_and_months(self):
        d = stats.compute(ROWS, "day", TODAY)
        self.assertEqual((len(d["series"]), d["series"][-1]["start"], d["series"][0]["start"]), (30, "2026-10-28", "2026-09-29"))
        self.assertFalse(d["series"][-1]["partial"])
        m = stats.compute(ROWS, "month", TODAY)
        self.assertEqual([(x["start"], x["end"]) for x in m["series"][-2:]], [("2026-09-01", "2026-09-30"), ("2026-10-01", "2026-10-31")])
        self.assertEqual((m["series"][-1]["added"], m["series"][-2]["added"], m["series"][-2]["interview"]), (4, 1, 1))
        self.assertEqual(m["series"][0]["start"], "2025-11-01")

    def test_by_kind(self):
        """Столбики по периодам раскладываются: работодатель, кадровое агентство, работодатель скрыт."""
        rows = [row(1, "2026-10-26"), {**row(2, "2026-10-27"), "agency": True}, {**row(3, "2026-10-27"), "company": "Анонимный работодатель"}]
        last = stats.compute(rows, "week", TODAY)["series"][-1]
        self.assertEqual(last["added"], 3)
        self.assertEqual(last["by_kind"]["added"], {"employer": 1, "agency": 1, "hidden": 1})

    def test_empty_profile(self):
        s = stats.compute([], "week", TODAY)
        self.assertEqual(s["totals"]["applied"], {"total": 0, "avg": 0.0, "prev": 0})
        self.assertEqual((s["waiting"], s["score"]["avg"], s["speed"]["to_answer"]["days"]), ([], None, None))

    def test_route(self):
        with TempProfile() as t:
            t.add_vacancy(1, "ИТ-директор", saved="27.10.2026")
            analysis.analyze(t.profile, log=lambda *_: None, ask=fake_model)
            result = next(t.profile.results.glob("01 *.md"))
            funnel.set_stage(result, "applied")
            app = A.App(t.profiles, ask=fake_model)
            s = app.handle("GET", "/api/stats", {"profile": ["example"], "step": ["day"]}, {})
            self.assertEqual(s["step"], "day")
            row = A.vacancy_rows(t.profile)[0]
            self.assertEqual(row["analyzed_on"], date.today().isoformat())
            self.assertEqual(stats.events(row)["applied"], date.today().isoformat())
            self.assertFalse(row["cover_sent"])
            analysis.write_letter(t.profile, result, ask=lambda *a: "Письмо.", log=lambda *_: None)
            analysis.mark_sent(t.profile, result, "cover", "", date.today().isoformat())
            self.assertTrue(A.vacancy_rows(t.profile)[0]["cover_sent"])


if __name__ == "__main__":
    unittest.main()
