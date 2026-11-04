"""Ссылка на отчётность компании на сайте ФНС (ГИР БО): по ИНН из вакансии или по названию."""
import unittest
import urllib.parse

from helpers import TempProfile

from vacancy_assistant import app as A, sites
from vacancy_assistant.textio import read_text, write_text


def query(link):
    return urllib.parse.unquote(link["url"].split("query=", 1)[1])


class Finance(unittest.TestCase):
    def test_inn(self):
        self.assertEqual(sites.find_inn("Работодатель: ПАО «МТС», ИНН: 7740000076."), "7740000076")
        self.assertEqual(sites.find_inn("инн 500100732259"), "500100732259")           # ИП — 12 цифр
        self.assertEqual(sites.find_inn("ИНН 7740000077"), "")                           # контрольная цифра не та
        self.assertEqual(sites.find_inn("ООО ИННОТЕХМЕТ, телефон 7740000076"), "")      # не после слова «ИНН»
        self.assertEqual(sites.find_inn("ИНН 77400000761"), "")                          # 11 цифр — не ИНН

    def test_link(self):
        by_name = sites.finance_link("ПАО «МТС» (группа МТС)")
        self.assertEqual((query(by_name), by_name["by_inn"]), ("МТС", False))
        self.assertTrue(by_name["url"].startswith("https://bo.nalog.gov.ru/search?query="))
        by_inn = sites.finance_link("ПАО «МТС»", "Реквизиты: ИНН 7740000076")
        self.assertEqual((query(by_inn), by_inn["by_inn"]), ("7740000076", True))
        self.assertIsNone(sites.finance_link("Анонимный работодатель"))
        self.assertIsNone(sites.finance_link("не указана"))
        self.assertTrue(sites.finance_link("Анонимный работодатель", "ИНН 7740000076")["by_inn"])   # ИНН всё равно точен

    def test_in_card(self):
        with TempProfile() as t:
            path = t.add_vacancy(1, "Директор по ИТ", company="ПАО «МТС»")
            app = A.App(t.profiles)
            card = lambda: app.handle("GET", "/api/vacancy", {"profile": ["example"], "n": ["1"]}, {})
            self.assertEqual(query(card()["finance"]), "МТС")
            write_text(path, read_text(path) + "\nИНН 7740000076\n")
            self.assertEqual(query(card()["finance"]), "7740000076")


if __name__ == "__main__":
    unittest.main()
