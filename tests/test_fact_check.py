"""Сверка письма и резюме под вакансию с фактами из резюме: числа и названия не из резюме, «о себе» и вакансии."""
import unittest

from helpers import TempProfile, fake_model

from vacancy_assistant import analysis, fact_check, vacancies as V

CLEAN = ("Откликаюсь на позицию ИТ-директора в ООО Пример 1. В «Пример Ритейл» перенёс 25 систем в облако, "
         "затраты снизились на 35%, руководил командой 60 человек. В Демо Логистик сократил время вывода изменений.")
INVENTED = "В Газпроме руководил командой 450 человек и внедрил SAP, а в «Пример Ритейл» — 25 систем."


class FactCheck(unittest.TestCase):
    def setUp(self):
        self.t = TempProfile().__enter__()
        self.p = self.t.profile
        self.vac = self.t.add_vacancy(1, "ИТ-директор", company="ООО Пример 1")
        self.src = fact_check.source(self.p, self.vac.read_text(encoding="utf-8"))

    def tearDown(self):
        self.t.__exit__()

    def test_clean_letter(self):
        """Только факты из резюме и компания из вакансии — отметок нет."""
        self.assertEqual(self.src.unverified(CLEAN), [])

    def test_invented(self):
        self.assertEqual(self.src.unverified(INVENTED), ["450", "Газпроме", "SAP"])

    def test_facts_and_forms(self):
        """«Дополнительно о себе» — тоже источник; падежи и сокращения названий («Сбербанке» — «Сбер»); ссылки,
        начало предложения и заголовки Markdown не проверяются; «1,2» и «1.2» — одно число."""
        self.p.write_facts("Пет-проект на Python с локальной LLM, бюджет 1,2 млн ₽. Работал в Сбер.")
        src = fact_check.source(self.p)
        self.assertEqual(src.unverified("В Сбербанке и в проекте на Python с LLM — бюджет 1.2 млн. "
                                        "Код: https://github.com/x/y12345\n## Включить\n**Выделить**: облако"), [])

    def test_card_versions(self):
        """Каждая версия письма в карточке — со списком «проверьте»; своя правка проверяется так же."""
        result = analysis.analyze(self.p, ask=fake_model, summary=False, log=lambda *_: None)[0]
        analysis.write_letter(self.p, result, ask=lambda *a: INVENTED, log=lambda *_: None)
        analysis.save_text(self.p, result, "cover", CLEAN, "edit")
        letters = V.vacancy_details(self.p, 1)["letters"]
        self.assertEqual([v["unverified"] for v in letters], [[], ["450", "Газпроме", "SAP"]])


if __name__ == "__main__":
    unittest.main()
