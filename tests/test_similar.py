"""«Хочу» выше у вакансий, похожих на свежие отклики: образцы, сходство, надбавка, выключатель."""
import unittest
from datetime import date

from helpers import TempProfile

from vacancy_assistant import app as A, funnel, similar, vacancies as V
from vacancy_assistant.textio import write_text

PAY = ("---\n\nРазвитие платёжного процессинга и эквайринга, микросервисы на Kubernetes, высоконагруженные сервисы, "
       "антифрод, интеграции с банками-партнёрами, команда разработки платформы. {extra}")
PLANT = ("---\n\nАвтоматизация завода: станки, цеха, MES и SCADA, промышленные контроллеры, сменные мастера, "
         "техническое обслуживание оборудования. {extra}")
TODAY = date(2026, 10, 30)


def row(n, title, applied="", want=5, company=None):
    hist = [{"stage": "applied", "date": applied}] if applied else []
    return {"n": n, "title": title, "company": company or f"Компания {n}", "want": want,
            "funnel": {"stage": "applied" if applied else "", "date": applied, "history": hist}}


def texts_for(rows, kinds):
    return {r["n"]: kinds[r["n"]].format(extra=f"вакансия {r['n']}") for r in rows}


class Bonus(unittest.TestCase):
    def setUp(self):
        self.rows = [row(1, "Технический директор (CTO)", "2026-10-20"), row(2, "CTO платёжного сервиса", "2026-10-15"),
                     row(3, "Технический директор финтех", "2026-10-01"), row(4, "CIO банка", "2026-09-20"),
                     row(5, "CTO / Chief Technology Officer", "2026-09-10"),
                     row(10, "Технический директор (СТО)"),          # похожа на три отклика CTO — +2
                     row(11, "Технический директор производства"),   # та же роль, другой текст — 0
                     row(12, "Бухгалтер")]                           # другая роль — 0
        kinds = {1: PAY, 2: PAY, 3: PAY, 4: PAY, 5: PLANT, 10: PAY, 11: PLANT, 12: PAY}
        self.texts = texts_for(self.rows, kinds)

    def test_bonus(self):
        got = similar.bonuses(self.rows, self.texts, TODAY)
        self.assertEqual(got[10]["bonus"], 2)
        self.assertEqual([x["n"] for x in got[10]["like"]], [1, 2, 3])        # CIO 4 — другая роль
        self.assertEqual(got[11]["bonus"], 1)                                 # похожа только на 5 (тоже завод)
        self.assertEqual([x["n"] for x in got[11]["like"]], [5])
        self.assertNotIn(12, got)
        self.assertFalse(set(got) & {1, 2, 3, 4, 5})                          # у откликов надбавки нет

    def test_old_and_few(self):
        """Отклики старше 90 дней — не образцы; меньше трёх образцов — надбавки нет."""
        self.assertEqual(similar.bonuses(self.rows, self.texts, date(2027, 1, 5)), {})       # остались 1 и 2
        self.assertEqual(len(similar.samples(self.rows, date(2026, 12, 30))), 3)              # 1, 2, 3 — до 01.10
        rows = [r for r in self.rows if r["n"] not in (3, 4, 5)]
        self.assertEqual(similar.bonuses(rows, self.texts, TODAY), {})

    def test_recent_ten(self):
        rows = [row(n, "CTO", f"2026-10-{n:02d}") for n in range(1, 13)]
        self.assertEqual([r["n"] for r in similar.samples(rows, TODAY)], list(range(12, 2, -1)))

    def test_duplicate_not_counted(self):
        """Та же вакансия ещё раз (одно название у одной компании) — не повод для надбавки."""
        rows = self.rows + [row(13, "Технический директор (CTO)", company="Компания 1")]
        texts = {**self.texts, 13: self.texts[1]}
        self.assertNotIn(1, [x["n"] for x in similar.bonuses(rows, texts, TODAY)[13]["like"]])

    def test_roles(self):
        self.assertEqual(similar.roles("Технический директор (СТО)"), {"cto"})
        self.assertEqual(similar.roles("ИТ-директор"), {"cio"})
        self.assertEqual(similar.roles("Генеральный директор ИТ-компании"), set())
        self.assertEqual(similar.roles("Директор по инвестициям / Chief Investment Officer (CIO)"), set())


class Rows(unittest.TestCase):
    def test_rows_and_switch(self):
        with TempProfile() as t:
            for n, text in ((1, PAY), (2, PAY), (3, PAY), (4, PAY), (5, PLANT)):
                path = t.add_vacancy(n, "Технический директор")
                write_text(path, path.read_text(encoding="utf-8") + text.format(extra=f"№{n}") + "\n")
                write_text(t.profile.results / path.name, f"---\n---\n<!-- {{\"title\": \"Технический директор\", \"company\": \"ООО Пример {n}\", \"link\": \"https://hh.ru/vacancy/{100000 + n}\", "
                           f"\"score\": 6, \"can\": 6, \"want\": 5, \"decision\": \"да\", \"stage\": \"full\"}} -->\n# Технический директор\n")
                if n <= 3:
                    funnel.set_stage(t.profile.results / path.name, "applied", date.today(), "new")
            rows = {r["n"]: r for r in V.vacancy_rows(t.profile)}
            self.assertEqual(rows[4]["want_bonus"], 2)
            self.assertEqual(rows[4]["want"], 5)                              # «Хочу» модели не меняется
            self.assertEqual(rows[5]["want_bonus"], 0)
            app = A.App(t.profiles, fetch_page=None, ask=None, check=lambda: {"ollama": True, "model_ok": True})
            app.handle("POST", "/api/profile/settings", {}, {"profile": "example", "want_similar": False})
            again = t.profile.__class__("example", t.profiles)                 # как после перезапуска
            self.assertFalse(similar.enabled(again))
            self.assertEqual({r["want_bonus"] for r in V.vacancy_rows(again)}, {0})


if __name__ == "__main__":
    unittest.main()
