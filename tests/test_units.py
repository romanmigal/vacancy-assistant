"""Небольшие функции: форматы файлов, имена, разбор страниц hh, резюме из PDF."""
import unittest

from helpers import SEARCH_HTML, VACANCY_HTML, TempProfile

from vacancy_assistant import files as F
from vacancy_assistant import hh, ratings, summary as S
from vacancy_assistant.errors import AssistantError
from vacancy_assistant.resume_pdf import hh_resume_markdown
from vacancy_assistant.textio import read_text, write_text


class Files(unittest.TestCase):
    def test_parse_answer_with_markdown_headings(self):
        from vacancy_assistant.files import parse_answer, strengths
        answer = ("### Критерии:\nК1: ✅ Москва\n\n### Могу: 9/10 — опыт есть\n### Хочу: 8/10 — интересно\n"
                  "### Оценка: 8/10\n\n### Сильные стороны:\n- бюджеты\n\n### Пробелы:\n- нет финтеха\n\n"
                  "### Откликаться: да, но с оговорками")
        self.assertEqual(parse_answer(answer), {"score": 8, "can": 9, "want": 8, "decision": "да, но с оговорками"})
        self.assertEqual(strengths(answer), "- бюджеты")                     # «Пробелы» в опору письма не попадают

    def test_parse_answer(self):
        r = F.parse_answer("**Могу:** 7/10 — x\nХочу: 9/10\nОценка: 8/10\n\nОткликаться: да, но с оговорками (уточнить)")
        self.assertEqual(r, {"score": 8, "can": 7, "want": 9, "decision": "да, но с оговорками"})
        self.assertEqual(F.parse_answer("что-то другое")["decision"], "?")

    def test_safe_name_for_mac_and_windows(self):
        self.assertEqual(F.safe_name("10 Директор [FinData, МТС] — R&C"), "10 Директор (FinData МТС) — R и C")
        self.assertEqual(F.safe_name('a:b*c?d"e<f>g|h/i\\j'), "abcdefghij")
        self.assertEqual(F.safe_name("Директор ИТ."), "Директор ИТ")          # точка в конце запрещена в Windows

    def test_md_path_uses_forward_slashes(self):
        self.assertEqual(F.md_path("разборы\\01 CIO (x).md"), "разборы/01%20CIO%20%28x%29.md")

    def test_yaml_scalar(self):
        self.assertEqual(F.yaml_scalar('"отклик: \\"ждём\\""'), 'отклик: "ждём"')
        self.assertEqual(F.yaml_scalar("'it''s'"), "it's")

    def test_decision_yes(self):
        self.assertEqual([F.decision_yes(x) for x in ("да", "да, но…", "нет", "?")], [True, True, False, None])

    def test_say_decision(self):
        """«да, но с оговорками» в журнале и Сводке — «возможно», как в окне."""
        self.assertEqual([F.say_decision(x) for x in ("да", "да, но с оговорками", "возможно", "нет", "?", None)],
                         ["да", "возможно", "возможно", "нет", "?", "?"])

    def test_files_are_written_with_unix_newlines(self):
        with TempProfile() as t:
            p = t.tmp / "x.md"
            write_text(p, "a\nb\n")
            self.assertEqual(p.read_bytes(), b"a\nb\n")
            p.write_bytes(b"c\r\nd\r\n")                                      # файл, записанный на Windows
            self.assertEqual(read_text(p), "c\nd\n")

    def test_notes(self):
        with TempProfile() as t:
            p = t.tmp / "r.md"
            write_text(p, "<!-- {} -->\nтекст\n")
            F.ensure_note_prop(p)
            self.assertEqual(F.read_note(p), "")
            write_text(p, read_text(p).replace('заметка: ""', 'заметка: "отклик: отказ"'))
            self.assertEqual(F.read_note(p), "отклик: отказ")


class HH(unittest.TestCase):
    def test_vacancy_page(self):
        title, company, text = hh.vacancy_markdown(VACANCY_HTML, "123456", saved="21.10.2026")
        self.assertEqual((title, company), ("ИТ-директор", "ООО Пример"))
        self.assertIn("**Зарплата:** от 500 000 ₽ за месяц на руки", text)
        self.assertIn("**Задачи:**\n\n- руководить ИТ\n- строить **команду**", text)
        self.assertIn("Вложенный блок", text)
        self.assertNotIn("после описания", text)

    def test_key_skills(self):
        self.assertFalse(hh.page_skills(VACANCY_HTML))
        page = VACANCY_HTML.replace("</body>", '<ul><li data-qa="skills-element"><div><div>Учет ТМЦ</div></div></li>'
                                    '<li data-qa="skills-element"><div>1С: &quot;Бухгалтерия&quot;</div></li>'
                                    '<li data-qa="skills-element"><div>Учет ТМЦ</div></li></ul></body>')
        text = hh.vacancy_markdown(page, "1")[2]
        self.assertTrue(text.endswith('\n\n**Ключевые навыки:** Учет ТМЦ, 1С: "Бухгалтерия"\n'))

    def test_set_skills(self):
        with TempProfile() as tp:
            path = tp.tmp / "v.md"
            write_text(path, "# Т\n\n---\n\nОписание\n")
            page = '<li data-qa="skills-element"><div>Учет ТМЦ</div></li><li data-qa="skills-element"><div>Excel</div></li>'
            self.assertTrue(hh.set_skills(path, page))
            self.assertEqual(read_text(path), "# Т\n\n---\n\nОписание\n\n**Ключевые навыки:** Учет ТМЦ, Excel\n")
            self.assertFalse(hh.set_skills(path, page))                       # повтор — без изменений
            self.assertTrue(hh.set_skills(path, page.replace("Excel", "1С")))  # навыки поменялись — строка заменена
            self.assertEqual(read_text(path).count("Ключевые навыки"), 1)
            self.assertFalse(hh.set_skills(path, "<html></html>"))           # навыков на странице нет — файл не трогаем

    def test_set_skills_keeps_description(self):
        with TempProfile() as tp:
            path = tp.tmp / "v.md"
            write_text(path, "# Т\n\n---\n\n**Ключевые навыки:** из описания\n\nОписание\n\n**Ключевые навыки:** старое\n")
            page = '<li data-qa="skills-element"><div>Учет ТМЦ</div></li><li data-qa="skills-element"><div>Excel</div></li>'
            self.assertTrue(hh.set_skills(path, page))
            text = read_text(path)                                           # заголовок из описания цел, обновлён хвост
            self.assertEqual(text, "# Т\n\n---\n\n**Ключевые навыки:** из описания\n\nОписание\n\n**Ключевые навыки:** Учет ТМЦ, Excel\n")
            self.assertEqual(text.count("**Ключевые навыки:**"), 2)
            # навыков ещё нет, а в описании такой заголовок — дописать в конец, заголовок не трогать
            write_text(path, "# Т\n\n---\n\n**Ключевые навыки:**\n\n- считать\n")
            self.assertTrue(hh.set_skills(path, page))
            self.assertEqual(read_text(path), "# Т\n\n---\n\n**Ключевые навыки:**\n\n- считать\n\n**Ключевые навыки:** Учет ТМЦ, Excel\n")

    def test_anonymous_and_unreadable(self):
        page = VACANCY_HTML.replace('data-qa="vacancy-company-name"', 'data-qa="other"')
        self.assertEqual(hh.vacancy_markdown(page, "1")[1], hh.ANONYMOUS)
        self.assertEqual(hh.vacancy_markdown("<html></html>", "1")[0], None)

    def test_search_page(self):
        self.assertEqual(hh.parse_search_page(SEARCH_HTML), [
            ("111111", "Технический директор (CTO)"), ("222222", "Начальник отдела ИТ"),
            ("333333", "Директор по информационным технологиям & цифре")])

    def test_search_reads_all_pages(self):
        page = lambda ids: "".join(f'<a data-qa="serp-item__title" href="/vacancy/{i}">В{i}</a>' for i in ids)
        pages = {0: page(range(1, 21)), 1: page(range(21, 41)), 2: page(range(41, 46))}
        fetch = lambda url: pages.get(int(url.rsplit("page=", 1)[1]), "")
        results, n = hh.search_pages("CTO", "area=1", 7, fetch, lambda s: None)
        self.assertEqual((len(results), n), (45, 3))                     # 3 страницы, а не потолок 40
        repeat = lambda url: page(range(1, 21))                          # hh повторяет одну страницу
        self.assertEqual(hh.search_pages("CTO", "area=1", 7, repeat, lambda s: None)[1], 1)

    def test_plural(self):
        self.assertEqual([hh.plural(n, "вакансия", "вакансии", "вакансий") for n in (1, 3, 11, 21, 40)],
                         ["1 вакансия", "3 вакансии", "11 вакансий", "21 вакансия", "40 вакансий"])

    def test_vacancy_ids(self):
        self.assertEqual(hh.vacancy_ids(["https://hh.ru/vacancy/138639828?from=a&hhtmFrom=main",
                                         "x https://spb.hh.ru/vacancy/222222 и hh.ru/vacancy/138639828"]),
                         ["138639828", "222222"])


class Profile(unittest.TestCase):
    def test_example_prompts(self):
        with TempProfile() as t:
            p = t.profile
            prompt = p.analysis_prompt("РЕЗЮМЕ", "ВАКАНСИЯ")
            self.assertIn("К4: ✅ / ❌ / ❓ — ...", prompt)                     # формат — по числу критериев
            self.assertNotIn("К5:", prompt)
            self.assertNotIn("{", prompt.replace("{resume}", ""))
            letter = p.letter_prompt("Р", "В", "С")
            self.assertIn("Иван Петров", letter)
            self.assertNotIn("{signature}", letter)

    def test_title_filter(self):
        with TempProfile() as t:
            fits = t.profile.title_fits
            self.assertTrue(fits("Директор по информационным технологиям (CIO)"))
            self.assertTrue(fits("Технический директор (CTO)"))
            self.assertFalse(fits("Начальник отдела ИТ"))
            self.assertFalse(fits("Директор по развитию бизнеса"))           # «ИТ» внутри «развИТия»


class Small(unittest.TestCase):
    def test_short_salary(self):
        self.assertEqual(S.short_salary("от 250 000 до 400 000 ₽ за месяц до вычета налогов"), "250–400 тыс. до налогов")
        self.assertEqual(S.short_salary("не указана"), "—")

    def test_parse_numbers(self):
        self.assertEqual(ratings.parse_numbers(["17", "20-22,30"]), [17, 20, 21, 22, 30])
        with self.assertRaises(AssistantError):
            ratings.parse_numbers(["5-x"])


class ResumePdf(unittest.TestCase):
    def test_markdown(self):
        text = "\n".join([
            "Иван Петров", "Мужчина, 40 лет, родился 1 января 1986", "+7 (900) 000-00-00", "ivan@example.com",
            "Опыт работы — 10 лет", "Июль 2023 —", "Июнь 2024", "1 год",
            "Май 2014 — Май", "2023", "9 лет", "ООО Альфа", "Москва, alfa.ru/", "Руководитель разработки",
            "— Вывел систему в эксплуатацию и снизил число", "инцидентов вдвое.",
            "ООО Бета", "Москва, www.beta.ru", "Разработчик",
            "Резюме обновлено 20 октября 2026", "Обо мне Люблю порядок."])
        md = hh_resume_markdown(text)
        self.assertTrue(md.startswith("# Иван Петров\n"))
        for private in ("+7", "@", "родился"):
            self.assertNotIn(private, md)
        self.assertIn("### Июль 2023 — Июнь 2024 (1 год)\nООО Альфа", md)     # периоды вернулись к компаниям
        self.assertIn("### Май 2014 — Май 2023 (9 лет)\nООО Бета", md)
        self.assertIn("- Вывел систему в эксплуатацию и снизил число инцидентов вдвое.", md)
        self.assertIn("## Обо мне\n\nЛюблю порядок.", md)


if __name__ == "__main__":
    unittest.main()
