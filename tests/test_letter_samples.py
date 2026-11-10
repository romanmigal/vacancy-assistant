"""Свои отправленные письма — образцы стиля для нового письма."""
import unittest

from helpers import TempProfile, fake_model

from vacancy_assistant import analysis, letter_samples as S
from vacancy_assistant.textio import read_text

LOG = dict(log=lambda *_: None)


def letter(body):
    return f"Здравствуйте!\n\n{body}\n\nБуду рад обсудить детали.\n\nИван Петров"


class Samples(unittest.TestCase):
    def setUp(self):
        self.t = TempProfile().__enter__()
        self.p = self.t.profile
        for n, title in ((1, "ИТ-директор"), (2, "Технический директор (CTO)"), (3, "CTO"), (4, "Директор по ИТ")):
            self.t.add_vacancy(n, title, company=f"ООО Пример {n}")
        self.r = analysis.analyze(self.p, ask=fake_model, summary=False, **LOG)

    def tearDown(self):
        self.t.__exit__()

    def send(self, i, body, source="edit", when="2026-11-10"):
        analysis.save_text(self.p, self.r[i], "cover", letter(body), source)
        analysis.mark_sent(self.p, self.r[i], "cover", when=when)

    def test_only_sent_own_letters(self):
        """Образец — своё или поправленное письмо с отметкой «Отправлено»; письмо модели и неотправленная правка — нет.
        В образце — середина письма, без рамки."""
        analysis.write_letter(self.p, self.r[0], ask=fake_model, **LOG)
        analysis.mark_sent(self.p, self.r[0], "cover", when="2026-11-10")
        analysis.save_text(self.p, self.r[1], "cover", letter("Не отправлено."), "edit")
        self.send(2, "Более 20 лет в ИТ.", "own")
        self.assertEqual([(x["name"][:2], x["text"]) for x in S.sent(self.p)], [("03", "Более 20 лет в ИТ.")])

    def test_pick_same_role_then_newest(self):
        """Сначала письма к той же роли, при равенстве — новее; письмо к этой же вакансии — не образец."""
        self.send(0, "Письмо CIO.", when="2026-11-08")
        self.send(1, "Письмо CTO старое.", when="2026-11-07")
        self.send(3, "Письмо CIO новое.", when="2026-11-09")
        self.assertEqual(S.pick(self.p, self.r[2].name, "CTO"), ["Письмо CTO старое.", "Письмо CIO новое."])
        self.assertEqual(S.pick(self.p, self.r[1].name, "Технический директор", count=1), ["Письмо CIO новое."])
        S.set_enabled(self.p, False)
        self.assertEqual(S.pick(self.p, self.r[2].name, "CTO"), [])

    def test_in_prompt(self):
        """Образцы — в промпте письма с пометкой «факты не брать»; без образцов блока нет."""
        self.send(0, "Более 20 лет в ИТ, люблю порядок.")
        prompts = []
        target = analysis.write_letter(self.p, self.r[2], ask=lambda prompt, *a: prompts.append(prompt) or "Середина.", **LOG)
        self.assertIn("=== МОИ ОТПРАВЛЕННЫЕ ПИСЬМА ===\n--- Письмо 1 ---\nБолее 20 лет в ИТ, люблю порядок.", prompts[0])
        self.assertIn("Факты, компании и цифры из них не бери", prompts[0])
        self.assertIn('"samples": 1', read_text(target).split("\n", 1)[0])
        S.set_enabled(self.p, False)
        analysis.write_letter(self.p, self.r[2], ask=lambda prompt, *a: prompts.append(prompt) or "Середина.", **LOG)
        self.assertNotIn("ОТПРАВЛЕННЫЕ", prompts[1])
        self.assertNotIn("{samples}", prompts[1])

    def test_requirements_in_prompt(self):
        """В промпт — требования с ✅ из разбора; требования с ❌ и пояснения к оценке — нет."""
        f = self.r[2]
        text = read_text(f).replace("Сильные стороны:", "Требования:\n- Опыт в ритейле — ✅ Пример Ритейл\n"
                                    "- Знание SAP — ❌ нет в резюме\n- Опыт покрывает почти всё.\n\nСильные стороны:")
        f.write_text(text, encoding="utf-8")
        prompts = []
        analysis.write_letter(self.p, f, ask=lambda prompt, *a: prompts.append(prompt) or "Середина.", **LOG)
        block = prompts[0].split("=== ТРЕБОВАНИЯ ВАКАНСИИ И МОЙ ОПЫТ ===\n")[1].split("\n===")[0]
        self.assertEqual(block, "- Опыт в ритейле — ✅ Пример Ритейл")
        self.assertNotIn("{requirements}", prompts[0])

    def test_earlier_letter_same_company(self):
        """Письмо, уже отправленное в эту компанию к другой вакансии (и версия модели), — в промпт: не повторять.
        Другая компания и «Анонимный работодатель» — нет."""
        self.t.add_vacancy(5, "CIO", company="ООО Пример 1")
        r5 = analysis.analyze(self.p, ask=fake_model, summary=False, **LOG)[0]
        analysis.write_letter(self.p, self.r[0], ask=lambda *a: "Первое письмо в Пример 1.", **LOG)
        analysis.mark_sent(self.p, self.r[0], "cover", when="2026-11-09")
        self.assertEqual(S.earlier(self.p, r5.name, "Пример 1"), "Первое письмо в Пример 1.")
        self.assertEqual(S.earlier(self.p, self.r[0].name, "ООО Пример 1"), "")       # своё письмо — не «прежнее»
        self.assertEqual(S.earlier(self.p, r5.name, "ООО Пример 2"), "")
        prompts = []
        analysis.write_letter(self.p, r5, ask=lambda prompt, *a: prompts.append(prompt) or "Середина.", **LOG)
        self.assertIn("=== ПИСЬМО, УЖЕ ОТПРАВЛЕННОЕ В ЭТУ КОМПАНИЮ ===\nПервое письмо в Пример 1.", prompts[0])
        self.assertNotIn("{earlier}", prompts[0])


if __name__ == "__main__":
    unittest.main()
