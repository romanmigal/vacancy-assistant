"""Вакансии из писем hh. Образцы писем в fixtures/письма/ — вымышленные: компании, номера, ключ входа."""
import base64
import json
import unittest
from pathlib import Path

from helpers import TempProfile

from vacancy_assistant import app as A, contacts, mails
from vacancy_assistant.errors import AssistantError
from vacancy_assistant.textio import read_text

LETTERS = Path(__file__).parent / "fixtures" / "письма"


def letter(name):
    return (LETTERS / f"{name}.eml").read_bytes()


class Read(unittest.TestCase):
    def test_saved_search(self):
        r = mails.read(letter("автопоиск"))
        self.assertEqual((r["kind"], r["date"]), ("Автопоиск", "2026-10-28"))
        self.assertEqual([i["id"] for i in r["items"]], ["900001", "900002", "900003"])
        self.assertEqual(r["items"][0], {"id": "900001", "title": "Технический директор (CTO)", "salary": "до 500 000 ₽ за месяц",
                                         "company": "Северный Ветер", "city": "Москва"})
        self.assertEqual((r["items"][1]["salary"], r["items"][1]["company"]), ("", "Ромашка"))

    def test_resume_recommendations(self):
        r = mails.read(letter("по резюме"))
        self.assertEqual(r["kind"], "Рекомендации по резюме")
        self.assertEqual([(i["id"], i["company"], i["city"]) for i in r["items"]], [("900003", "Ромашка", ""), ("900004", "Лесная Компания", "")])

    def test_no_login_key_anywhere(self):
        """В ссылках писем hh — ключ входа в аккаунт: из ссылки берётся только номер."""
        for name in ("автопоиск", "по резюме"):
            out = json.dumps(mails.read(letter(name)), ensure_ascii=False)
            self.assertNotIn("TESTKEY", out)
            self.assertNotIn("http", out)

    def test_other_letters(self):
        with self.assertRaisesRegex(AssistantError, "Хабр"):
            mails.read(letter("хабр"))
        with self.assertRaisesRegex(AssistantError, "не письмо hh"):
            mails.read(letter("чужое"))
        with self.assertRaises(AssistantError):
            mails.read(b"\x00\x01 not a letter")


class Inbox(unittest.TestCase):
    def test_new_seen_added(self):
        with TempProfile() as t:
            t.add_vacancy(4, "ИТ-директор", "Лесная Компания")
            path = next(t.profile.vacancies.glob("04 *.md"))
            path.write_text(read_text(path).replace("vacancy/100004", "vacancy/900004"), encoding="utf-8")
            contacts.save(t.profile, [{"id": "c1", "name": "Иван", "company": "Ромашка"}])
            r = mails.inbox(t.profile, [("a.eml", letter("автопоиск")), ("b.eml", letter("по резюме")), ("h.eml", letter("хабр"))])
            self.assertEqual(len(r["letters"]), 2)
            self.assertEqual(len(r["problems"]), 1)
            self.assertTrue(r["problems"][0].startswith("h.eml: "))
            by = {i["id"]: i for i in r["items"]}
            self.assertEqual(list(by), ["900001", "900002", "900003", "900004"])            # 900003 из двух писем — один раз
            self.assertEqual(by["900004"]["state"], "added")
            self.assertEqual(by["900004"]["n"], 4)
            self.assertEqual([by[k]["fits"] for k in ("900001", "900002")], [True, False])
            self.assertEqual(by["900003"]["contacts"], 1)
            seen = read_text(t.profile.seen)
            self.assertIn("900001\t", seen)
            self.assertIn(f"\t{mails.MARK}\t", seen)
            self.assertNotIn("900004", seen)
            self.assertNotIn("TESTKEY", seen)
            again = mails.inbox(t.profile, [("a.eml", letter("автопоиск"))])                # то же письмо ещё раз
            self.assertEqual({i["state"] for i in again["items"]}, {"seen"})

    def test_route(self):
        with TempProfile() as t:
            app = A.App(t.profiles, fetch_page=lambda url: self.fail("письма не ходят на hh"), ask=None,
                        check=lambda: {"ollama": True, "model_ok": True})
            files = [{"name": "a.eml", "data": base64.b64encode(letter("автопоиск")).decode()}]
            res = app.handle("POST", "/api/mails", {}, {"profile": "example", "files": files})
            self.assertEqual(len(res["items"]), 3)
            self.assertIn("hh_auto", res)


if __name__ == "__main__":
    unittest.main()
