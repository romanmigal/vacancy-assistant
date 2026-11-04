"""Резюме из файла без модели: выгрузка hh в «TXT» (HTML), PDF по правилам, простой текст."""
import unittest

from helpers import FIXTURES

from vacancy_assistant.errors import AssistantError
from vacancy_assistant.resume_pdf import file_markdown, hh_resume_markdown

SAMPLE = FIXTURES / "резюме"


class ResumeFile(unittest.TestCase):
    def test_hh_html(self):
        md = file_markdown((SAMPLE / "Смирнова — выгрузка hh.html").read_bytes())
        for private in ("+7", "@", "родилась", "Женщина", "3 марта 1985", "способ связи", "Резюме обновлено"):
            self.assertNotIn(private, md)
        self.assertTrue(md.startswith("# Смирнова Анна\nПроживает: Санкт-Петербург\n"
                                      "Гражданство: Россия, есть разрешение на работу: Россия\n"))
        self.assertEqual(md.count("\n### "), 2)
        self.assertIn("### Апрель 2019 — настоящее время (7 лет 7 месяцев)\nООО «Северный Завод Металлоконструкций»\n"
                      "Санкт-Петербург, szmk.example/\nПромышленное оборудование, техника, станки\n- Металлообработка\n"
                      "Финансовый директор\nОтвечаю за финансы завода.\n\n**Достижения:**\n"
                      "- Построила казначейство и сократила кассовые разрывы вдвое;\n", md)
        self.assertIn("### Февраль 2014 — Март 2019 (5 лет 2 месяца)\nООО «Балтийская Логистическая Компания»", md)
        self.assertIn("**Санкт-Петербургский государственный экономический университет, Санкт-Петербург** — 2007, "
                      "Экономика, Бухгалтерский учёт и аудит", md)
        self.assertIn("**Знание языков**\n- Русский — Родной\n- Английский — B2 — Средне-продвинутый", md)
        self.assertIn("**Навыки**\nБюджетирование; МСФО; Казначейство", md)
        self.assertIn("Сильные стороны:\n- казначейство и управление ликвидностью;\n- работа с банками", md)

    def test_pdf_text_by_rules(self):
        md = hh_resume_markdown((SAMPLE / "Смирнова — текст PDF.txt").read_text(encoding="utf-8"))
        self.assertIn("### Февраль 2014 — Март 2019 (5 лет 2 месяца)\nООО «Балтийская Логистическая Компания»", md)

    def test_page_numbers(self):
        md = hh_resume_markdown("Иван\nВместо подрядчика из\n20\nсотрудников.\n2\nКонец")
        self.assertIn("подрядчика из\n20 сотрудников.", md)              # «20» — часть фразы, не номер страницы
        self.assertNotIn("\n2\n", md)                                    # номер страницы

    def test_plain_text_and_bad_files(self):
        md = file_markdown("Иван Петров\n+7 900 000-00-00\nivan@example.com\nОпыт: 10 лет\n".encode("cp1251"))
        self.assertEqual(md, "Иван Петров\nОпыт: 10 лет\n")
        for data in (b"PK\x03\x04docx", "<html><body><div>Новости</div></body></html>".encode()):
            with self.assertRaises(AssistantError):
                file_markdown(data)


if __name__ == "__main__":
    unittest.main()
