"""Рамка сопроводительного письма: приветствие, готовность, завершение и подпись ставит программа, модель — середину."""
import unittest

from helpers import TempProfile, fake_model

from vacancy_assistant import analysis, letter_frame, settings, setup
from vacancy_assistant.textio import read_text

BODY = "Откликаюсь на позицию CTO.\n\nПохожие задачи я решал раньше:\n— в Банке построил ИТ с нуля."


class Frame(unittest.TestCase):
    def setUp(self):
        self.t = TempProfile().__enter__()
        self.p = self.t.profile
        self.p.config["письмо"].update({"готовность": "Могу приступить сразу.", "завершение": "Буду рад обсудить детали.",
                                        "подпись": "Роман Мигаль"})

    def tearDown(self):
        self.t.__exit__()

    def test_strip_what_model_wrote(self):
        """Модель написала свои приветствие, готовность, завершение и подпись из резюме — остаётся середина."""
        for answer in (f"Здравствуйте!\n\n{BODY}\n\nМогу приступить сразу.\n\nБуду рад обсудить детали.\n\nМигаль Роман Анатольевич",
                       f"Добрый день, команда Ромашки!\n{BODY}\nГотов приступить через месяц.\nС уважением,\nРоман Мигаль",
                       f"{BODY}\n\nБуду рад обсудить детали.\nРоман Мигаль",
                       f"{BODY}\n\nМогу приступить через две недели. Буду рад обсудить детали.\n\nИван Петров",
                       f"{BODY}\n\nБуду рад обсудить детали.\n\n[Cандидат]",     # GigaChat: метка маски с латинской C
                       BODY):
            self.assertEqual(letter_frame.strip_frame(answer, self.p), BODY, answer)

    def test_keeps_format_sentence(self):
        """Согласие с форматом работы после фразы о готовности остаётся: его разрешает промпт."""
        body = letter_frame.strip_frame(f"{BODY}\n\nМогу приступить сразу. Удалённый формат мне подходит.\n\nРоман Мигаль", self.p)
        self.assertEqual(body, BODY + "\n\nУдалённый формат мне подходит.")

    def test_assemble(self):
        self.assertEqual(letter_frame.assemble(self.p, "Здравствуйте!", BODY),
                         f"Здравствуйте!\n\n{BODY}\n\nМогу приступить сразу.\n\nБуду рад обсудить детали.\n\nРоман Мигаль")
        self.assertEqual(letter_frame.assemble(self.p, "", BODY + "\n\nУдалённый формат мне подходит."),   # одной строкой с готовностью
                         f"{BODY}\n\nМогу приступить сразу. Удалённый формат мне подходит.\n\nБуду рад обсудить детали.\n\nРоман Мигаль")
        self.p.config["письмо"]["готовность"] = ""                       # «не писать»: фразы о готовности нет
        self.assertEqual(letter_frame.assemble(self.p, "", BODY + "\n\nУдалённый формат мне подходит."),
                         f"{BODY}\n\nУдалённый формат мне подходит.\n\nБуду рад обсудить детали.\n\nРоман Мигаль")
        self.assertEqual(letter_frame.assemble(self.p, "", BODY), f"{BODY}\n\nБуду рад обсудить детали.\n\nРоман Мигаль")

    def test_split_example(self):
        """Шаблон: приветствие — в письмо, середина — модели как образец, без готовности, завершения и подписи."""
        example = f"Добрый день!\n\n{BODY}\n\nМогу приступить через две недели.\n\nБуду рад обсудить детали.\n\nРоман Мигаль\n"
        self.assertEqual(letter_frame.split_example(example, self.p), ("Добрый день!", BODY))
        self.assertEqual(letter_frame.split_example(BODY, self.p), ("", BODY))

    def test_write_letter(self):
        """Письмо в файле — в рамке из профиля, даже если модель подписалась иначе; модели — образец без рамки."""
        self.t.add_vacancy(1, "CTO")
        result = analysis.analyze(self.p, log=lambda *_: None, ask=fake_model, summary=False)[0]
        prompts = []
        answer = f"Здравствуйте!\n\n{BODY}\n\nМогу приступить сразу.\n\nМигаль Роман Анатольевич"
        target = analysis.write_letter(self.p, result, ask=lambda prompt, *a: prompts.append(prompt) or answer, log=lambda *_: None)
        text = read_text(target).split("\n---\n", 1)[1].strip()
        self.assertTrue(text.endswith(f"{BODY}\n\nМогу приступить сразу.\n\nБуду рад обсудить детали.\n\nРоман Мигаль"), text)
        self.assertEqual(text.count("Могу приступить"), 1)
        self.assertNotIn("Анатольевич", text)
        self.assertIn(settings.LETTER_TEMPLATE.name, read_text(target).split("\n", 1)[0])
        example = prompts[0].split("=== ОБРАЗЕЦ ===")[1].split("=== КОНЕЦ ОБРАЗЦА ===")[0]
        self.assertNotIn("Буду рад обсудить детали.", example)

    def test_prompt_follows_sample(self):
        """Форму и длину письма задаёт образец: в промпте нет зашитого списка «— в <компания>», объём — ± 20% от образца."""
        prompt = self.p.letter_prompt("Резюме", "Вакансия", "- опыт", "x" * 500)
        self.assertIn("от 400 до 600 знаков", prompt)
        self.assertNotIn("{min_chars}", prompt)
        self.assertNotIn("— в <компания>", prompt)
        self.assertIn("абзацем-обзором", prompt)

    def test_wizard_start_off(self):
        self.assertEqual(setup.START["не писать"], "")
        cfg = setup.build_config({"name": "Мария Иванова", "start": "не писать", "field": "финансы"})
        self.assertEqual(cfg["письмо"]["готовность"], "")
        setup.update_profile(self.p, {"start": "не писать"}, log=lambda *_: None)     # правка в мастере и обратно
        self.assertEqual(setup.answers_from_profile(self.p)["start"], "не писать")
        self.assertEqual(self.p.config["письмо"]["готовность"], "")


if __name__ == "__main__":
    unittest.main()
