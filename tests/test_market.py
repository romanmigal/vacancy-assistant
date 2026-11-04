"""Резюме против рынка: слова из вакансий с откликом, требования с ❌, проверка на ATS, «было → стало»."""
import unittest
from datetime import date

from helpers import TempProfile

from vacancy_assistant import app as A, funnel, market
from vacancy_assistant.textio import read_json, write_text

ANSWER = """Критерии:
К1: ✅ — Москва

Требования:
1. Опыт внедрения ITIL и Service Desk — ❌ (в резюме нет)
2. {second} — ❌ (нет)
3. Управление командой от 50 человек — ✅ (Пример Ритейл)

Могу: 5/10 — частично
Хочу: 8/10 — интересно
Оценка: {score}/10

Сильные стороны: команда
Пробелы: ITIL

Откликаться: да"""


def setup(t, n, text, score=7, second="Опыт с Kafka", stage="applied"):
    path = t.add_vacancy(n, f"ИТ-директор {n}", f"Компания {n}")
    write_text(path, path.read_text(encoding="utf-8") + text + "\n")
    write_text(t.profile.results / path.name, f"---\n---\n<!-- {{\"title\": \"ИТ-директор {n}\", \"company\": \"Компания {n}\", "
               f"\"score\": {score}, \"can\": 5, \"want\": 8, \"decision\": \"да\", \"stage\": \"full\"}} -->\n# ИТ-директор {n}\n\n"
               + ANSWER.format(score=score, second=second))
    if stage:
        funnel.set_stage(t.profile.results / path.name, stage, date(2026, 10, 20), "new")


class Terms(unittest.TestCase):
    def test_terms(self):
        found = market.terms("Опыт CI/CD, ITSM/ITIL, Power BI и disaster recovery; experience with Docker and Kubernetes; ЦОД, ИБ, ООО «Ромашка»")
        self.assertEqual(set(found), {"cicd", "itsm", "itil", "powerbi", "disasterrecovery", "docker", "kubernetes", "цод",
                                      "информационнаябезопасность"})

    def test_synonyms(self):
        self.assertEqual(market.norm("итил"), "itil")
        self.assertEqual(market.norm("PnL"), "p&l")
        self.assertEqual(market.norm("1С"), "1c")
        self.assertEqual(market.norm("k8s"), "kubernetes")

    def test_cluster(self):
        groups = market.cluster([("Опыт внедрения AI/ML в продукты", 1), ("Опыт построения AI Native Engineering", 2),
                                 ("Опыт работы в производственном бизнесе", 3), ("Внедрение AI-native подходов", 4)])
        self.assertEqual(groups[0]["vacancies"], [2, 4])           # «AI Native» и «AI-native подходы» — одно
        self.assertEqual([g["count"] for g in groups[1:]], [1, 1])


class Report(unittest.TestCase):
    def test_report(self):
        with TempProfile() as t:
            for n in range(1, 5):
                setup(t, n, "Требования: ITIL, Kafka, Kubernetes, Python. Команда 50 человек.", score=8 if n < 4 else 4,
                      stage="rejected" if n == 4 else "applied")
            setup(t, 5, "Требования: 1С, SAP.", score=9, stage=None)      # без отклика — не в счёт, даже с оценкой 9
            r = A.App(t.profiles, fetch_page=None, ask=None, check=lambda: {"ollama": True, "model_ok": True}) \
                .handle("POST", "/api/market", {}, {"profile": "example"})
            self.assertEqual(r["vacancies"], 4)                   # любой этап, и «Отказ»; оценка не важна
            words = {w["term"]: w for w in r["words"] if not w["in_resume"]}
            self.assertEqual(set(words), {"ITIL", "Kafka", "Kubernetes", "Python"})
            self.assertNotIn("SAP", words)
            self.assertEqual(r["gaps"][0]["count"], 4)            # ITIL и Service Desk — во всех четырёх разборах
            self.assertIn("ITIL", r["gaps"][0]["text"])
            self.assertEqual(r["missing"], 4)
            self.assertEqual(read_json(t.profile.dir / market.FILE)["history"][-1]["missing"], 4)

    def test_word_in_facts_counts(self):
        with TempProfile() as t:
            for n in range(1, 4):
                setup(t, n, "Нужны ITIL и Kafka.")
            t.profile.write_facts("Внедрил процессы по итил в Пример Ритейл")
            words = {w["term"]: w["in_resume"] for w in market.report(t.profile, A.vacancy_rows(t.profile))["words"]}
            self.assertEqual((words["ITIL"], words["Kafka"]), (True, False))

    def test_progress(self):
        with TempProfile() as t:
            rep = {"missing": 5, "gaps": [1], "vacancies": 3}
            market.remember(t.profile, rep, date(2026, 10, 1))
            market.remember(t.profile, {**rep, "missing": 3}, date(2026, 10, 2))
            market.remember(t.profile, {**rep, "missing": 2}, date(2026, 10, 2))   # тот же день — одна запись
            hist = read_json(t.profile.dir / market.FILE)["history"]
            self.assertEqual([(h["date"], h["missing"]) for h in hist], [("2026-10-01", 5), ("2026-10-02", 2)])

    def test_empty(self):
        with TempProfile() as t:
            r = market.report(t.profile, [])
            self.assertEqual((r["vacancies"], r["words"], r["gaps"]), (0, [], []))


class Ats(unittest.TestCase):
    def test_example_resume(self):
        with TempProfile() as t:
            checks = {c["text"].split(" —")[0]: c["ok"] for c in market.ats(t.profile.read_resume())}
            self.assertTrue(checks["Раздел «Опыт работы»"])
            self.assertTrue(checks["Даты работы"])
            self.assertFalse(checks["Длина"])                     # пример короткий

    def test_bad_resume(self):
        bad = {c["text"].split(" —")[0]: c["ok"] for c in market.ats("Иван\n| a | b |\n| 1 | 2 |\n" + "текст " * 400)}
        self.assertFalse(bad["Раздел «Опыт работы»"])
        self.assertFalse(bad["Без таблиц"])


class Advice(unittest.TestCase):
    def test_advice(self):
        with TempProfile() as t:
            for n in range(1, 4):
                setup(t, n, "Нужны ITIL и Kafka.")
            asked = []
            ask = lambda prompt, *a: asked.append(prompt) or "### ITIL\n**Было:** в резюме этого нет\n**Стало:** в резюме этого нет — добавьте, если это правда"
            market.write_advice(t.profile, A.vacancy_rows(t.profile), lambda *_: None, ask)
            self.assertIn("ITIL", asked[0])
            self.assertIn("Перевод ИТ в облако", asked[0])                # резюме — в запросе
            saved = market.report(t.profile, A.vacancy_rows(t.profile))["advice"]
            self.assertIn("**Было:**", saved["text"])
            self.assertEqual(saved["vacancies"], 3)

    def test_route_needs_model(self):
        with TempProfile() as t:
            title, work = A.make_work(t.profile, "market_advice", {})
            self.assertIn("Резюме против рынка", title)


if __name__ == "__main__":
    unittest.main()
