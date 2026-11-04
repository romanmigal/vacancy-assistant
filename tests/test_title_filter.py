"""Отбор по названию: «СТО» кириллицей, «Технический директор» без слов про ИТ, автосервисы;
перепроверка отсеянных."""
import unittest
from datetime import date

from helpers import TempProfile

from vacancy_assistant import hh
from vacancy_assistant.profile import Profile, plain_title
from vacancy_assistant.textio import read_text, write_text


class TitleFilter(unittest.TestCase):
    def setUp(self):
        self.t = TempProfile().__enter__()
        self.p = self.t.profile                       # профиль-пример — сфера ИТ, как у мастера для ИТ-директора

    def tearDown(self):
        self.t.__exit__(None, None, None)

    def test_passes(self):
        for title in ("Технический директор (СТО)", "Технический директор (CTO)", "СIO", "IТ-директор",
                      "Технический директор по разработке / Head of Engineering", "Технический директор",
                      "Технический директор портфеля продуктов", "Директор по ИТ на производстве"):
            self.assertTrue(self.p.title_fits(title), title)

    def test_filtered(self):
        for title in ("Мастер-приемщик (СТО премиум-сегмента General Motors)",
                      "Руководитель развития региональных СТО/территориальный руководитель",
                      "Технический директор СТО/Старший мастер-приемщик",
                      "Технический директор (пищевое производство)", "Технический директор (ЖКХ)",
                      "Производственный директор / Технический директор", "Технический директор регионального завода",
                      "Коммерческий директор B2B IT (CCO/Chief Commercial Officer)", "Финансовый директор"):
            self.assertFalse(self.p.title_fits(title), title)

    def test_plain_title(self):
        self.assertEqual(plain_title("Технический директор (СТО)"), "Технический директор (CTO)")
        self.assertEqual(plain_title("IТ-директор"), "IT-директор")
        self.assertEqual(plain_title("Директор СТО сети"), "Директор СТО сети")       # автосервис — как было
        self.assertEqual(plain_title("Директор ООО «СОК»"), "Директор ООО «СОК»")       # не аббревиатура должности

    def test_not_it_profile(self):
        p = Profile("example", self.t.profiles)
        p.config["поиск"]["название_про_сферу"] = {"слова": [], "части": ["финанс"]}
        p.save_config()
        p = Profile("example", self.t.profiles)
        self.assertFalse(p.title_fits("Технический директор"))                    # правило — только для сферы ИТ
        self.assertTrue(p.title_fits("Финансовый директор"))

    def test_own_industries(self):
        p = Profile("example", self.t.profiles)
        p.config["поиск"]["другие_отрасли"] = ["телеком"]
        p.save_config()
        p = Profile("example", self.t.profiles)
        self.assertFalse(p.title_fits("Технический директор (телеком)"))
        self.assertTrue(p.title_fits("Технический директор (ЖКХ)"))               # свой список вместо общего

    def test_recheck(self):
        write_text(self.p.seen, "".join(f"{v}\t{d}\t{m}\t{t}\n" for v, d, m, t in [
            ("1001", "27.10.2026", "отсеяна", "Технический директор (СТО)"),
            ("1002", "27.10.2026", "отсеяна", "Технический директор (ЖКХ)"),        # и сейчас не проходит
            ("1003", "01.10.2026", "отсеяна", "Технический директор"),             # старше 14 дней
            ("1004", "20.10.2026", "отсеяна", "Технический директор"),
            ("1004", "21.10.2026", "взята", "Технический директор"),               # потом взяли
            ("1005", "26.10.2026", "отсеяна", "IТ-директор"),
            ("1006", "26.10.2026", "по ссылке", "ИТ-директор"),
        ]))
        self.t.add_vacancy(1, "Технический директор")                              # 100001 добавили по ссылке
        write_text(self.p.seen, read_text(self.p.seen) + "100001\t27.10.2026\tотсеяна\tТехнический директор\n")
        items = hh.recheck_filtered(self.p, today=date(2026, 10, 28))
        self.assertEqual([r["id"] for r in items], ["1001", "1005"])
        self.assertEqual(items[0], {"id": "1001", "date": "2026-10-27", "title": "Технический директор (СТО)"})


if __name__ == "__main__":
    unittest.main()
