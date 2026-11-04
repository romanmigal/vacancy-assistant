"""Дата публикации вакансии в карточке (#46): из разметки JobPosting или из строки hh «Вакансия опубликована…»."""
import json
import unittest
from pathlib import Path

from helpers import TempProfile

from vacancy_assistant import app as A, hh, sites
from vacancy_assistant.files import read_vacancy
from vacancy_assistant.textio import read_text

PAGES = Path(__file__).parent / "fixtures" / "страницы"
HH_LINE = read_text(PAGES / "hh-вакансия с датой.html")          # только строка «Вакансия опубликована 20 октября 2026»
HH_PLAIN = read_text(PAGES / "hh-вакансия.html")                  # даты нет
LD = ('<script type="application/ld+json">' + json.dumps({"@type": "JobPosting", "title": "CTO", "datePosted": "2026-09-03T10:15:00+03:00",
      "hiringOrganization": {"name": "ООО Ромашка"}, "description": "<p>" + "Руководить разработкой. " * 20 + "</p>"}) + "</script>")


class Posted(unittest.TestCase):
    def test_sources(self):
        self.assertEqual(hh.posted(HH_PLAIN.replace("</head>", LD + "</head>")), "03.09.2026")   # сначала datePosted
        self.assertEqual(hh.posted(HH_LINE), "20.10.2026")
        self.assertEqual(hh.posted(HH_PLAIN), "")
        self.assertEqual(hh.posted("<p>Вакансия опубликована&nbsp;5&nbsp;мая&nbsp;2026 в Казани</p>"), "05.05.2026")

    def test_hh_file(self):
        text = hh.vacancy_markdown(HH_LINE, "987654322")[2]
        self.assertIn("**Опубликовано:** 20.10.2026  \n**Сохранено:**", text)
        self.assertNotIn("Опубликовано", hh.vacancy_markdown(HH_PLAIN, "987654321")[2])

    def test_saved_pages(self):
        with TempProfile() as t:
            path = sites.add_saved(t.profile, HH_LINE, log=lambda *_: None)
            self.assertEqual(read_vacancy(path)[1]["posted"], "20.10.2026")
            other = sites.add_saved(t.profile, f"<html><head><title>CTO — Ромашка</title>{LD}</head><body></body></html>",
                                    log=lambda *_: None)
            self.assertEqual(read_vacancy(other)[1]["posted"], "03.09.2026")
            row = next(r for r in A.vacancy_rows(t.profile) if r["n"] == 1)
            self.assertEqual(row["posted"], "20.10.2026")

    def test_no_date_site(self):
        info = sites.from_page("<html><head><title>CTO — Ромашка</title></head><body><main>" + "Текст. " * 80 + "</main></body></html>",
                               "https://example.com/job/1")
        self.assertNotIn("Опубликовано", sites.vacancy_file(info, "https://example.com/job/1"))

    def test_update(self):
        """hh подняла вакансию — дата публикации в файле меняется; в тексте карточки строки нет."""
        with TempProfile() as t:
            path = t.add_vacancy(1, "CTO")
            self.assertTrue(hh.set_posted(path, "20.10.2026"))
            self.assertFalse(hh.set_posted(path, "20.10.2026"))
            self.assertTrue(hh.set_posted(path, "28.10.2026"))
            text = read_text(path)
            self.assertEqual(text.count("Опубликовано"), 1)
            self.assertEqual(read_vacancy(path)[1]["posted"], "28.10.2026")
            self.assertNotIn("Опубликовано", A.without_saved(text))
            self.assertNotIn("Сохранено", A.without_saved(text))


if __name__ == "__main__":
    unittest.main()
