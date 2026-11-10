"""«Моя оценка»: «Могу», «Хочу» и дата в мои-оценки.md, расчётная общая, поля строки таблицы, сортировка колонки."""
import json
import re
import shutil
import subprocess
import unittest
from datetime import date, datetime
from pathlib import Path

from helpers import TempProfile

from vacancy_assistant import ratings, vacancies as V
from vacancy_assistant.errors import AssistantError
from vacancy_assistant.textio import read_text, write_text

CORE = Path(__file__).resolve().parent.parent / "vacancy_assistant" / "web" / "js" / "core.js"
OLD_TABLE = """# Мои оценки вакансий

| №   | Вакансия | Моя оценка (1–10) | Откликаться? | Почему (1–2 фразы) |
| --- | -------- | ----------------- | ------------ | ------------------ |
| 01  | ИТ-директор — ООО Пример | 7 | да | интересно |
"""


class Ratings(unittest.TestCase):
    def test_date_written(self):
        with TempProfile() as t:
            t.add_vacancy(1, "ИТ-директор")
            ratings.set_rating(t.profile, 1, 8, 9, "возможно", "далеко ехать", today=date(2026, 11, 3))
            row = ratings.read_rows(t.profile)[1]
            self.assertEqual((row["score"], row["can"], row["want"], row["decision"], row["date"]),
                             (9, 8, 9, "да, но с оговорками", "2026-11-03"))
            self.assertIn("| Дата |", read_text(t.profile.ratings))
            self.assertEqual(ratings.read_reference(t.profile)[1]["yes"], True)     # эталон калибровки читается как раньше

    def test_old_table_without_date(self):
        with TempProfile() as t:
            t.add_vacancy(1, "ИТ-директор")
            t.add_vacancy(2, "CTO")
            write_text(t.profile.ratings, OLD_TABLE)
            self.assertEqual(ratings.read_rows(t.profile)[1]["date"], "")           # старая оценка — без даты
            ratings.set_rating(t.profile, 2, 4, 4, "нет", "", today=date(2026, 11, 3))
            text = read_text(t.profile.ratings)
            self.assertEqual(text.count("| Дата | Могу | Хочу |"), 1)               # колонки добавлены в заголовок
            self.assertIn("| ---- |", text)
            rows = ratings.read_rows(t.profile)
            self.assertEqual((rows[1]["score"], rows[1]["date"], rows[1]["can"], rows[2]["date"]), (7, "", None, "2026-11-03"))

    def test_row_fields(self):
        with TempProfile() as t:
            t.add_vacancy(1, "ИТ-директор")
            t.add_vacancy(2, "CTO")
            ratings.set_rating(t.profile, 1, 5, 8, "возможно", "далеко", today=date(2026, 11, 2))
            got = {r["n"]: (r["my_score"], r["my_can"], r["my_want"], r["my_decision"], r["my_date"], r["my_reason"])
                   for r in V.vacancy_rows(t.profile)}
            self.assertEqual(got, {1: (6, 5, 8, "возможно", "2026-11-02", "далеко"), 2: (None, None, None, "", "", "")})

    def test_history(self):
        """Своя оценка — событие в «Истории» вакансии; повтор той же оценки — не событие."""
        with TempProfile() as t:
            t.add_vacancy(1, "ИТ-директор")
            ratings.set_rating(t.profile, 1, 5, 8, "возможно", "далеко", when=datetime(2026, 11, 2, 10, 0))
            ratings.set_rating(t.profile, 1, 5, 8, "возможно", "далеко", when=datetime(2026, 11, 2, 11, 0))
            ratings.set_rating(t.profile, 1, 3, 8, "нет", "нет | разработки", when=datetime(2026, 11, 3, 9, 30))
            got = V.vacancy_details(t.profile, 1)["ratings"]
            self.assertEqual([(e["date"], e["time"], e["score"], e["can"], e["want"], e["decision"], e["reason"]) for e in got],
                             [("2026-11-02", "10:00:00", 6, 5, 8, "возможно", "далеко"),
                              ("2026-11-03", "09:30:00", 4, 3, 8, "нет", "нет / разработки")])

    def test_history_of_old_rating(self):
        """Оценка до записи истории — одной записью по дате из таблицы; совсем старая, без даты, — ничего."""
        with TempProfile() as t:
            t.add_vacancy(1, "ИТ-директор")
            write_text(t.profile.ratings, OLD_TABLE)
            self.assertEqual(V.vacancy_details(t.profile, 1)["ratings"], [])
            write_text(t.profile.ratings, read_text(t.profile.ratings).replace("| интересно |", "| интересно | 01.11.2026 | | |"))
            got = V.vacancy_details(t.profile, 1)["ratings"]
            self.assertEqual([(e["date"], e["time"], e["score"], e["decision"]) for e in got], [("2026-11-01", "", 7, "да")])

    def test_total(self):
        """Общая — середина «Могу» и «Хочу», не выше меньшей + 1; при «нет» — не выше 4."""
        cases = [((8, 9, "да"), 9), ((3, 9, "да"), 4), ((7, 8, "нет"), 4), ((2, 2, "нет"), 2), ((10, 10, "да"), 10)]
        for args, want in cases:
            self.assertEqual(ratings.total(*args), want, args)

    def test_bad_input(self):
        with TempProfile() as t:
            t.add_vacancy(1, "ИТ-директор")
            for can, want, dec in ((None, 5, "да"), (11, 5, "да"), (5, 5, "может быть")):
                with self.assertRaises(AssistantError):
                    ratings.set_rating(t.profile, 1, can, want, dec)


@unittest.skipUnless(shutil.which("node"), "нет node")
class Total(unittest.TestCase):
    def test_js_same_as_python(self):
        """Общая в окне (core.js) считается так же, как при сохранении (ratings.total)."""
        code = read_text(CORE)
        fn = re.search(r"^const myTotal = .*?^};", code, re.M | re.S).group(0)
        cases = [(c, w, d) for c in range(1, 11) for w in range(1, 11) for d in ("да", "возможно", "нет")]
        script = fn + f"\nconsole.log(JSON.stringify({json.dumps(cases, ensure_ascii=False)}.map(a => myTotal(...a))));"
        out = json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout)
        self.assertEqual(out, [ratings.total(*c) for c in cases])


@unittest.skipUnless(shutil.which("node"), "нет node")
class Sort(unittest.TestCase):
    def test_order(self):
        """По убыванию: свежая дата выше; в одной дате — да, возможно, нет; дальше — оценка; без даты — ниже."""
        code = read_text(CORE)
        snippet = "\n".join(re.search(rf"^const {name} = .*$", code, re.M).group(0) for name in ("MY_RANK", "myKey"))
        rows = [{"n": 1, "my_decision": "нет", "my_score": 3, "my_date": "2026-11-03"},
                {"n": 2, "my_decision": "да", "my_score": 6, "my_date": "2026-11-03"},
                {"n": 3, "my_decision": "да", "my_score": 9, "my_date": "2026-11-03"},
                {"n": 4, "my_decision": "возможно", "my_score": 7, "my_date": "2026-11-03"},
                {"n": 5, "my_decision": "да", "my_score": 10, "my_date": "2026-11-01"},
                {"n": 6, "my_decision": "да", "my_score": 8, "my_date": ""},
                {"n": 7, "my_decision": "", "my_score": None, "my_date": ""}]
        script = snippet + f"""
const rows = {json.dumps(rows, ensure_ascii=False)};
const rated = rows.filter(r => myKey(r) != null).sort((a, b) => myKey(b).localeCompare(myKey(a)));
console.log(JSON.stringify([rated.map(r => r.n), rows.filter(r => myKey(r) == null).map(r => r.n)]));"""
        out = json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout)
        self.assertEqual(out, [[3, 2, 4, 1, 5, 6], [7]])


if __name__ == "__main__":
    unittest.main()
