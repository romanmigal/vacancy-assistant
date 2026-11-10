"""Эталон писем: сравнение версий промпта на своих и поправленных письмах профиля — вымышленный пример."""
import unittest

from helpers import TempProfile, fake_model

from vacancy_assistant import analysis, letter_bench as B
from vacancy_assistant.textio import read_text

HUMAN = "Здравствуйте!\n\nВ Ромашке построил ИТ с нуля за год.\n\nБуду рад обсудить детали.\n\nИван Петров"


def model(prompt, *a):
    """v2 — письмо целиком, v3 — середина: в обоих выдуманные «Сбербанк» и число 77."""
    body = "В «Пример Ритейл» снизил затраты на 35%. В Сбербанке сократил затраты на 77%."
    return f"Здравствуйте!\n\n{body}\n\nИван Петров" if "{signature}" not in prompt else body


class Bench(unittest.TestCase):
    def setUp(self):
        self.t = TempProfile().__enter__()
        self.p = self.t.profile
        self.p.config["письмо"].update({"готовность": "Могу приступить сразу.", "завершение": "Буду рад обсудить детали.",
                                        "подпись": "Иван Петров"})
        for n in (1, 2):
            self.t.add_vacancy(n, "CTO", company=f"ООО Пример {n}")
        self.results = analysis.analyze(self.p, log=lambda *_: None, ask=fake_model, summary=False)

    def tearDown(self):
        self.t.__exit__()

    def test_reference_only_human_letters(self):
        """В эталоне — вакансии со своим или поправленным письмом; письмо модели — нет. Отправленная версия важнее последней."""
        analysis.write_letter(self.p, self.results[0], ask=fake_model, log=lambda *_: None)
        self.assertEqual(B.reference(self.p), [])
        target = analysis.save_text(self.p, self.results[1], "cover", HUMAN, "edit")
        analysis.mark_sent(self.p, self.results[1], "cover", when="2026-11-10")
        analysis.save_text(self.p, self.results[1], "cover", "Черновик", "own")
        items = B.reference(self.p)
        self.assertEqual([(i["number"], i["source"], i["human"]) for i in items], [(2, "edit", HUMAN)])
        self.assertTrue(target.exists())

    def test_report(self):
        """Отчёт сравнивает две версии промпта, файлы писем профиля не меняются."""
        analysis.save_text(self.p, self.results[0], "cover", HUMAN, "own")
        before = sorted(f.name for f in self.p.letters.rglob("*.md"))
        out = self.t.tmp / "отчёт.md"
        B.run(self.p, ["v2", "v3"], out=out, log=lambda *_: None, asks={"тест": model})
        self.assertEqual(sorted(f.name for f in self.p.letters.rglob("*.md")), before)
        text = read_text(out)
        self.assertIn("| письмо v2 | тест | 1 |", text)
        self.assertIn("| письмо v3 | тест | 1 |", text)
        self.assertIn("рамка 3/3", text)                    # v3: рамку поставила программа
        self.assertIn("рамка 1/3", text)                    # v2: модель написала только подпись
        self.assertIn("«Сбербанке»", text)
        self.assertEqual(text.count("не из резюме: «77», «Сбербанке»\n"), 2)   # «Пример Ритейл» и 35% — из резюме

    def test_metrics(self):
        source = "Руководил ИТ в Банк Элемент, команда 40 человек, SAP."
        self.assertEqual(B.unsupported("Начал в Банк Элемент: 40 человек, SAP и Kubernetes, «Альфа», 120 серверов. "
                                       "Затем 2 года.", source), ["120", "Kubernetes", "Альфа"])
        share, common = B.repeats(["я руководил ИТ в банке и вывел продукт на рынок за год",
                                   "я руководил ИТ в банке и вывел продукт на рынок за два года", "другое письмо о складе"])
        self.assertEqual(common, [("я руководил ит в банке и вывел продукт на рынок за", 2)])
        self.assertGreater(share, 0.5)
        self.assertAlmostEqual(B.closeness("Руководил ИТ в банке", "руководила ИТ банка"), 1.0)

    def test_args(self):
        self.assertEqual(B.parse_args(["v2", "--models", "local", "--only", "128,130", "письмо v3.txt", "--out", "x.md"]),
                         (["v2", "письмо v3.txt"], ("local",), {128, 130}, "x.md"))
        self.assertEqual([f.name for f in B.prompt_files(["v2", "письмо v3"])], ["письмо v2.txt", "письмо v3.txt"])


if __name__ == "__main__":
    unittest.main()
