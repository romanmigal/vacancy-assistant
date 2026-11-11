"""Окно «Зарплаты»: разбор вилок, «на руки» ↔ «до вычета» по НДФЛ, курс ЦБ раз в день, итоги и группы."""
import unittest
from datetime import date
from pathlib import Path

from helpers import TempProfile

from vacancy_assistant import app as A, salaries as S
from vacancy_assistant.textio import write_text


class Parse(unittest.TestCase):
    def test_cases_from_issue(self):
        self.assertEqual(S.parse("от 500 000 ₽ на руки"), {"low": 500000, "high": None, "net": True, "currency": "RUB"})
        self.assertEqual(S.parse("300–400 тыс. до вычета"), {"low": 300000, "high": 400000, "net": False, "currency": "RUB"})
        self.assertEqual(S.parse("$5000"), {"low": 5000, "high": None, "net": False, "currency": "USD"})
        self.assertIsNone(S.parse("не указана"))
        self.assertIsNone(S.parse("По договорённости"))
        self.assertEqual(S.parse("до 400 000 ₽ за месяц до вычета налогов")["high"], 400000)

    def test_short_place(self):
        """Длинные типы поселений и районов в группах «По городу» — короче; короткие и обычные города — как есть."""
        self.assertEqual(S.where_format("**Где:** посёлок городского типа Новоивановское, офис"), ("Новоивановское", "офис"))
        self.assertEqual(S.short_place("Новомосковский административный округ"), "Новомосковский АО")
        self.assertEqual(S.short_place("г. Казань"), "Казань")
        for same in ("посёлок Шушары", "деревня Раздоры", "Городец", "Санкт-Петербург"):
            self.assertEqual(S.short_place(same), same)

    def test_point(self):
        self.assertEqual(S.point(S.parse("от 300 000 до 600 000 ₽")), 450000)
        self.assertEqual(S.point(S.parse("до 400 000 ₽")), 400000)

    def test_ndfl(self):
        self.assertEqual(S.to_net(100_000), 87_000)                         # 1,2 млн в год — всё по 13 %
        # 300 тыс. в месяц = 3,6 млн в год: 2,4 млн по 13 % и 1,2 млн по 15 %
        self.assertAlmostEqual(S.to_net(300_000), 300_000 - (2_400_000 * .13 + 1_200_000 * .15) / 12)
        for gross in (100_000, 300_000, 1_000_000, 5_000_000):
            self.assertAlmostEqual(S.to_gross(S.to_net(gross)), gross, places=4)


    def test_calc(self):
        r = S.calc(800_000)                                                  # «800 тыс. до вычета» в месяц
        self.assertEqual((r["gross"], r["net"], r["tax_year"]), (800_000, 672_500, 1_530_000))
        self.assertEqual(r["net_year"], 8_070_000)
        self.assertEqual(r["net"], round(S.to_net(800_000)))                 # те же числа, что у вилок в окне
        self.assertEqual([(m["from"], m["to"], m["net"], m["rates"]) for m in r["months"]],
                         [(1, 3, 696_000, [13]), (4, 6, 680_000, [15]), (7, 7, 662_000, [15, 18]), (8, 12, 656_000, [18])])
        self.assertEqual(sum(m["net"] * (m["to"] - m["from"] + 1) for m in r["months"]), r["net_year"])
        back = S.calc(672_500, net=True)                                     # и наоборот: на руки → до вычета
        self.assertEqual((back["gross"], back["net"]), (800_000, 672_500))
        self.assertEqual(S.calc(9_600_000, year=True)["gross"], 800_000)
        self.assertEqual(S.calc(10_000, currency="USD", rate={"USD": 80.0})["gross"], 800_000)
        self.assertEqual(S.calc(100_000)["months"], [{"from": 1, "to": 12, "net": 87_000, "rates": [13]}])


class Rates(unittest.TestCase):
    def setUp(self):
        self.t = TempProfile().__enter__()
        self.folder = Path(self.t.profiles)

    def tearDown(self):
        self.t.__exit__(None, None, None)

    def test_once_a_day_and_fallback(self):
        calls = []
        fetch = lambda: calls.append(1) or {"USD": 80.0}
        day = date(2026, 10, 29)
        self.assertEqual(S.rates(self.folder, day, fetch), ({"USD": 80.0}, "2026-10-29", ""))
        S.rates(self.folder, day, fetch)
        self.assertEqual(len(calls), 1)                                          # второй раз — из кэша

        def down():
            raise OSError("нет сети")
        rate, when, note = S.rates(self.folder, date(2026, 10, 30), down)
        self.assertEqual((rate, when), ({"USD": 80.0}, "2026-10-29"))           # прежний курс с его датой
        self.assertIn("29", note)
        (self.folder / S.RATES_FILE).unlink()
        self.assertEqual(S.rates(self.folder, day, down)[0], {})


class Report(unittest.TestCase):
    def setUp(self):
        self.t = TempProfile().__enter__()
        t = self.t
        t.add_vacancy(1, "ИТ-директор", salary="от 500 000 ₽ за месяц на руки")
        t.add_vacancy(2, "Директор по ИТ", salary="300–400 тыс. до вычета")
        t.add_vacancy(3, "CIO", salary="$5000")
        t.add_vacancy(4, "Руководитель ИТ", salary="не указана")
        path = t.add_vacancy(5, "Начальник отдела", salary="от 200 000 до 300 000 ₽ за месяц на руки")
        write_text(path, path.read_text(encoding="utf-8").replace("**Ссылка:**", "**Где:** Москва, гибрид  \n**Ссылка:**"))
        self.app = A.App(t.profiles)
        self.app.fetch_rates = lambda: {"USD": 80.0}

    def tearDown(self):
        self.t.__exit__(None, None, None)

    def report(self):
        return self.app.handle("GET", "/api/salaries", {"profile": ["example"]}, {})

    def test_report(self):
        r = self.report()
        self.assertEqual((r["total"], r["with_salary"], r["without"]), (5, 4, 1))
        nets = {p["n"]: p["net"] for p in r["points"]}
        self.assertEqual(nets[1], 500_000)
        self.assertEqual(nets[3], round(S.to_net(400_000)))                     # $5000 × 80, до вычета
        self.assertEqual(nets[5], 250_000)
        self.assertEqual(r["rates"], {"USD": 80.0})
        self.assertEqual(r["net"]["median"], round((nets[2] + nets[3]) / 2))   # 250 тыс., №2, №3, 500 тыс.
        five = next(p for p in r["points"] if p["n"] == 5)
        self.assertEqual((five["city"], five["format"]), ("Москва", "гибрид"))
        self.assertIn("CIO", [g["label"] for g in r["groups"]["level"]])

    def test_without_rates(self):
        def down():
            raise OSError("нет сети")
        self.app.fetch_rates = down
        r = self.report()
        self.assertEqual((r["with_salary"], r["skipped"]), (3, [3]))
        self.assertIn("не пересчитаны", r["note"])

    def test_no_foreign_no_request(self):
        (self.t.profile.vacancies / "03 CIO — ООО Пример.md").unlink()
        self.app.fetch_rates = lambda: self.fail("курс не нужен")
        self.assertEqual(self.report()["rates"], {})

    def calc(self, **a):
        return self.app.handle("GET", "/api/salaries/calc", {"profile": ["example"], **{k: [v] for k, v in a.items()}}, {})

    def test_calc_route(self):
        self.assertEqual(self.calc(amount="800000")["net"], 672_500)
        self.assertEqual(self.calc(amount="672500", net="1")["gross"], 800_000)
        r = self.calc(amount="120000", currency="USD", period="year")           # $10 000 в месяц по 80 ₽
        self.assertEqual((r["gross"], r["rate"]), (800_000, 80.0))
        self.app.fetch_rates = lambda: self.fail("курс не нужен")
        self.assertIsNone(self.calc(amount="800000")["rate"])

    def test_calc_errors(self):
        with self.assertRaisesRegex(Exception, "число"):
            self.calc(amount="много")
        with self.assertRaisesRegex(Exception, "валюты"):
            self.calc(amount="1000", currency="XYZ")
        def down():
            raise OSError("нет сети")
        self.app.fetch_rates = down
        with self.assertRaisesRegex(Exception, "Курс ЦБ"):
            self.calc(amount="1000", currency="EUR")

    def test_planka(self):
        r = S.compute(S.items(self.t.profile), planka=400_000, rate={"USD": 80.0})
        self.assertEqual(r["planka"], 400_000)
        self.assertEqual(r["above"]["net"], 1)                                 # на руки 400+ — только №1


if __name__ == "__main__":
    unittest.main()


class Amount(unittest.TestCase):
    """Сумма в калькуляторе окна: salAmount в web/js/salaries.js — через node, если он есть."""

    def test_amount(self):
        import json
        import shutil
        import subprocess
        node = shutil.which("node")
        if not node:
            self.skipTest("нет node")
        import re
        js = (Path(S.__file__).parent / "web" / "js" / "salaries.js").read_text(encoding="utf-8")
        js = re.search(r"^function salAmount\(.*?^}", js, re.S | re.M).group(0)          # остальное — про страницу
        cases = {"300000": 300000, "300 000": 300000, "300 000 ₽": 300000, "400 тыс.": 400000, "400тыс": 400000,
                 "250k": 250000, "1,2 млн": 1200000, "1.5m": 1500000, "$5000": None, "много": None, "": None}
        script = js + f"\nconsole.log(JSON.stringify({json.dumps(list(cases))}.map(salAmount)));"
        out = subprocess.run([node, "-e", script], capture_output=True, text=True).stdout
        self.assertEqual(dict(zip(cases, json.loads(out))), cases)
