"""Трекер контактов: сверка компаний, выгрузка LinkedIn, кандидаты в референсеры."""
import io
import unittest
import zipfile

from helpers import TempProfile

from vacancy_assistant import contacts
from vacancy_assistant.errors import AssistantError

CSV = """Notes:
"When exporting your connection data, you may notice that some of the email addresses are missing."

First Name,Last Name,URL,Email Address,Company,Position,Connected On
Иван,Петров,https://www.linkedin.com/in/ivan,,MTS,CFO,01 Feb 2020
Ольга,Смирнова,https://www.linkedin.com/in/olga,olga@example.com,Sberbank,Head of IT,03 Mar 2021
Anna,Lee,https://www.linkedin.com/in/anna,,"Tinkoff, Moscow",HR,05 May 2022
"""


class Contacts(unittest.TestCase):
    def test_company_match(self):
        m = contacts.match_level
        self.assertEqual(m("ПАО МТС", "MTS"), 2)
        self.assertEqual(m("Т-Банк", "Tinkoff"), 2)
        self.assertEqual(m("Яндекс", "Yandex"), 2)
        self.assertEqual(m("Роял Кредит Банк (группа «Диалект»)", "Royal Credit Bank"), 2)
        for vacancy, contact in (("Дойче Банк", "Deutsche Bank"), ("ПАО Московская биржа", "Moscow Exchange"),
                                 ("АО «Райффайзенбанк»", "Raiffeisenbank Russia"), ("Сбербанк-Технологии", "Sberbank Technology"),
                                 ("БНП Париба", "BNP Paribas CIB"), ("КИТ Финанс", "KIT Finance"), ("Люксофт", "Luxoft")):
            self.assertEqual(m(vacancy, contact), 2, vacancy)       # кириллица в вакансии, латиница в LinkedIn
        for contact in ("ВТБ", "VTB", "VTB Bank", "VTB Capital", "ВТБ Капитал"):     # «Банк» в начале — не имя
            self.assertEqual(m("Банк ВТБ (ПАО), Технологический блок", contact), 2, contact)
        for contact in ("Банк Элемент", "Bank of America", "Альфа-Банк", "Сбербанк"):  # общее слово «банк» — не повод
            self.assertEqual(m("Банк ВТБ (ПАО)", contact), 0, contact)
        self.assertEqual(m("VTB Capital", "Альфа Капитал"), 0)
        self.assertEqual(m("ВТБ Факторинг", "ВТБ"), 1)
        self.assertEqual(m("МТС Банк", "MTS"), 1)                    # похожая — показываем со знаком «?»
        self.assertEqual(m("ООО Пример", "Example"), 0)
        self.assertEqual(m("Анонимный работодатель", "Anon"), 0)

    def test_kh_and_junk(self):
        """«х» и «ch» после c→k пишутся одинаково; «Self-employed» и подобное — не компания."""
        self.assertEqual(contacts.latin("Технологии")[:7], contacts.latin("Technology")[:7])
        for junk in ("Self-employed", "Freelance", "Фриланс", "Индивидуальный предприниматель", "Stealth Startup"):
            self.assertEqual(contacts.match_level(junk, junk), 0, junk)
            self.assertEqual(contacts.match_level("Сбер", junk), 0, junk)

    def test_profile_synonyms(self):
        """Синоним профиля — точное совпадение, «разные» убирают похожее; у другого профиля синонимов нет."""
        with TempProfile() as t, TempProfile() as other:
            p = t.profile
            contacts.save(p, [{"id": "c1", "name": "Иван Петров", "company": "MTS"},
                              {"id": "c2", "name": "Ольга", "company": "Garant Tech"}])
            self.assertEqual(contacts.match_level("Гарант-Софт", "Garant Tech"), 1)
            self.assertEqual([c["exact"] for c in contacts.candidates(p, "МТС Банк")], [False])
            contacts.mark_same(p, "МТС Банк", "MTS")
            self.assertEqual([c["exact"] for c in contacts.candidates(p, "МТС Банк")], [True])
            self.assertEqual(contacts.match_level("МТС Банк", "MTS", contacts.synonyms(other.profile)), 1)   # другой профиль
            contacts.mark_apart(p, "Гарант-Софт", "Garant Tech")
            self.assertEqual(contacts.candidates(p, "Гарант-Софт"), [])
            with self.assertRaises(AssistantError):                     # одна компания — сначала разъединить
                contacts.mark_apart(p, "МТС Банк", "MTS")
            contacts.mark_same(p, "MTS", "MTS Digital")            # группы с общим названием сливаются
            syn = contacts.synonyms(p)
            self.assertEqual(syn.groups, [["МТС Банк", "MTS", "MTS Digital"]])
            contacts.mark_same(p, "Гарант-Софт", "Garant Tech")           # передумали: одна компания — пара «разные» уходит
            syn = contacts.synonyms(p)
            self.assertEqual((syn.apart, contacts.match_level("Гарант-Софт", "Garant Tech", syn)), ([], 2))
            contacts.save_synonyms(p, [], [])
            self.assertEqual(contacts.match_level("МТС Банк", "MTS", contacts.synonyms(p)), 1)

    def test_linkedin_import_and_candidates(self):
        with TempProfile() as t:
            p = t.profile
            r = contacts.import_linkedin(p, CSV.encode("utf-8"), "Connections.csv")
            self.assertEqual((r["read"], r["added"], r["total"]), (3, 3, 3))
            ivan = next(c for c in contacts.load(p) if c["name"] == "Иван Петров")
            contacts.upsert(p, {**ivan, "status": "wrote", "note": "учились вместе"})
            # повторная загрузка — архивом: дублей нет, должность обновилась, статус и заметка на месте
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as z:
                z.writestr("Connections.csv", CSV.replace("MTS,CFO", "MTS,CEO"))
            r = contacts.import_linkedin(p, buf.getvalue(), "Basic_LinkedInDataExport.zip")
            self.assertEqual((r["added"], r["updated"], r["total"]), (0, 1, 3))
            ivan = next(c for c in contacts.load(p) if c["name"] == "Иван Петров")
            self.assertEqual((ivan["position"], ivan["status"], ivan["note"]), ("CEO", "wrote", "учились вместе"))
            contacts.upsert(p, {"name": "Пётр Сидоров", "company": "МТС Банк", "position": "CIO"})   # вручную
            found = contacts.candidates(p, "ПАО МТС")
            self.assertEqual([(c["name"], c["exact"]) for c in found], [("Иван Петров", True), ("Пётр Сидоров", False)])
            self.assertEqual(contacts.candidates(p, "Т-Банк")[0]["name"], "Anna Lee")
            contacts.delete(p, ivan["id"])
            self.assertEqual(len(contacts.load(p)), 3)

    def test_linkedin_merges_manual_contact(self):
        with TempProfile() as t:
            p = t.profile
            contacts.upsert(p, {"name": "Алексей Помазной", "company": "Возможно Билайн", "status": "wrote", "note": "вендор"})
            row = "Aleksei,Pomaznoy,https://www.linkedin.com/in/ap,,Beeline,Account Manager,01 Feb 2020\n"
            r = contacts.import_linkedin(p, (CSV + row).encode(), "Connections.csv")
            self.assertEqual((r["added"], r["conflicts"], r["total"]), (3, 1, 4))           # тот же человек — без дубля
            ap = next(c for c in contacts.load(p) if c["url"].endswith("/ap"))
            self.assertEqual((ap["name"], ap["company"], ap["status"]), ("Алексей Помазной", "Beeline", "wrote"))
            self.assertEqual(ap["note"], "вендор · раньше: компания Возможно Билайн")

    def test_bad_files(self):
        with TempProfile() as t:
            with self.assertRaises(AssistantError):
                contacts.import_linkedin(t.profile, b"name,company\nx,y\n", "contacts.csv")
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as z:
                z.writestr("Profile.csv", "x")
            with self.assertRaises(AssistantError) as e:                              # базовый архив — по составу
                contacts.import_linkedin(t.profile, buf.getvalue(), "export.zip")
            self.assertIn("Complete", str(e.exception))
            with self.assertRaises(AssistantError) as e:                              # базовый архив — по имени
                contacts.import_linkedin(t.profile, buf.getvalue(), "Basic_LinkedInDataExport_10-23-2026.zip.zip")
            self.assertIn("вторым письмом", str(e.exception))
            other = io.BytesIO()
            with zipfile.ZipFile(other, "w") as z:
                z.writestr("photo.jpg", "x")
            with self.assertRaises(AssistantError) as e:
                contacts.import_linkedin(t.profile, other.getvalue(), "photos.zip")
            self.assertIn("не выгрузка LinkedIn", str(e.exception))
            full = io.BytesIO()
            with zipfile.ZipFile(full, "w") as z:
                z.writestr("Connections.csv", CSV)
            r = contacts.import_linkedin(t.profile, full.getvalue(), "Complete_LinkedInDataExport_10-24-2026.zip.zip")
            self.assertEqual(r["added"], 3)                                          # «…zip.zip» читается
            with self.assertRaises(AssistantError):
                contacts.upsert(t.profile, {"company": "МТС"})                       # без имени


if __name__ == "__main__":
    unittest.main()
