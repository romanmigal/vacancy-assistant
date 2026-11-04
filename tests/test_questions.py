"""Вопросы работодателю во вкладке «Интервью» (#17): тем же вызовом, что истории STAR, или отдельно —
к подготовке, где их ещё нет; прежний раздел заменяется, истории остаются."""
import unittest

from helpers import TempProfile, fake_model

from vacancy_assistant import analysis, settings
from vacancy_assistant.textio import read_text, write_text


class Questions(unittest.TestCase):
    def setUp(self):
        self.t = TempProfile().__enter__()
        self.t.add_vacancy(1, "Директор по ИТ")
        analysis.analyze(self.t.profile, log=lambda *_: None, ask=fake_model)
        self.result = next(self.t.profile.results.glob("01 *.md"))

    def tearDown(self):
        self.t.__exit__(None, None, None)

    def test_prompts(self):
        prompts = []
        ask = lambda prompt, *a: prompts.append(prompt) or fake_model(prompt)
        analysis.write_interview(self.t.profile, self.result, log=lambda *_: None, ask=ask)
        self.assertIn("## Мои вопросы работодателю", prompts[0])
        self.assertIn("корпоративная культура", prompts[0])                    # общие вопросы — запрещены
        self.assertIn("Директор по ИТ", prompts[0])                            # вакансия в промпте
        analysis.write_questions(self.t.profile, self.result, log=lambda *_: None, ask=ask)
        self.assertIn("Подготовь только вопросы работодателю", prompts[1])
        self.assertNotIn("по методу STAR", prompts[1])
        self.assertTrue(settings.QUESTIONS_TEMPLATE.exists())

    def test_added_to_old_preparation(self):
        target = self.t.profile.interview / self.result.name
        self.t.profile.interview.mkdir(exist_ok=True)
        old = ("<!-- {} -->\n# Подготовка к интервью: Директор по ИТ\n\n---\n\n## 1. Запуск ИТ с нуля\n**Ситуация:** банк\n\n"
               "## Где будут спрашивать о пробелах\n- нет BPM\n")                # подготовка прежней версии — без вопросов
        write_text(target, old)
        logs = []
        analysis.write_questions(self.t.profile, self.result, log=logs.append, ask=fake_model)
        text = read_text(target)
        self.assertTrue(text.startswith(old.rstrip()))                         # прежнее — как было
        self.assertTrue(text.rstrip().endswith("3. Кто в команде? — пойму, с кем работать"))
        self.assertIn("вопросов — 3", logs[-1])
        analysis.write_questions(self.t.profile, self.result, log=lambda *_: None, ask=fake_model)
        self.assertEqual(read_text(target).count("## Мои вопросы работодателю"), 1)   # ещё раз — заменили, не дописали

    def test_answer_without_heading_and_middle_section(self):
        target = self.t.profile.interview / self.result.name
        self.t.profile.interview.mkdir(exist_ok=True)
        write_text(target, "# П\n\n## 1. История\nтекст\n\n## Мои вопросы работодателю\n1. старый\n\n## Заметки\nмои\n")
        analysis.write_questions(self.t.profile, self.result, log=lambda *_: None,
                                 ask=lambda *a: "1. Новый вопрос? — зачем\n2. Ещё? — зачем")   # модель забыла заголовок
        text = read_text(target)
        self.assertIn("## Мои вопросы работодателю\n1. Новый вопрос?", text)
        self.assertNotIn("старый", text)
        self.assertIn("## Заметки\nмои", text)                                  # раздел после вопросов — на месте

    def test_new_stories_keep_questions(self):
        analysis.write_interview(self.t.profile, self.result, log=lambda *_: None, ask=fake_model)
        analysis.write_questions(self.t.profile, self.result, log=lambda *_: None, ask=fake_model)
        prompts = []
        ask = lambda prompt, *a: prompts.append(prompt) or fake_model(prompt)
        path = analysis.write_interview(self.t.profile, self.result, log=lambda *_: None, ask=ask)   # «Подготовить заново»
        self.assertNotIn("Мои вопросы работодателю", prompts[0])               # просим только истории
        text = read_text(path)
        self.assertIn("## 1. Запуск ИТ с нуля", text)
        self.assertIn("1. Какой бюджет ИТ на год?", text)                      # вопросы — прежние
        self.assertEqual(text.count("## Мои вопросы работодателю"), 1)
        self.assertIn('"prompt": "интервью v1.txt"', text)

    def test_without_preparation_makes_full(self):
        path = analysis.write_questions(self.t.profile, self.result, log=lambda *_: None, ask=fake_model)
        text = read_text(path)
        self.assertIn("## 1. Запуск ИТ с нуля", text)                           # подготовки не было — делаем целиком
        self.assertIn("## Мои вопросы работодателю", text)


if __name__ == "__main__":
    unittest.main()
