"""Окно локальной модели: промпт, который не влез, — понятная ошибка; длинная вакансия обрезается с конца."""
import io
import json
import unittest
from unittest import mock

from helpers import TempProfile

from vacancy_assistant import model, profile as P, settings, setup
from vacancy_assistant.errors import AssistantError


def ollama(read):
    """Поддельный ответ Ollama: read — сколько токенов промпта она прочитала (prompt_eval_count)."""
    def urlopen(request, timeout=None):
        return io.BytesIO(json.dumps({"response": " Ответ ", "prompt_eval_count": read}).encode("utf-8"))
    return mock.patch.object(model.urllib.request, "urlopen", urlopen)


class Window(unittest.TestCase):
    def setUp(self):
        self.t = TempProfile().__enter__()
        self.p = self.t.profile

    def tearDown(self):
        self.t.__exit__()

    def test_truncated_prompt_is_error(self):
        """Ollama прочитала меньше, чем может быть токенов в таком тексте, и не больше окна — начало отрезано."""
        prompt = "Инструкция. " + "текст вакансии " * 4000              # 60 тыс. знаков — не меньше 13 тыс. токенов
        with ollama(12000), self.assertRaises(AssistantError) as e:
            model.ask_local(prompt, options=settings.OPTIONS)
        self.assertIn("не поместился в окно", str(e.exception))
        with ollama(17000):                                            # прочитала весь (новые Ollama читают за окном)
            self.assertEqual(model.ask_local(prompt, options=settings.OPTIONS), "Ответ")
        with ollama(1500):                                             # обычный промпт
            self.assertEqual(model.ask_local("Короткий промпт " * 300, options=settings.OPTIONS), "Ответ")

    def test_long_vacancy_cut_from_end(self):
        """Вакансия, которая не помещается вместе с резюме, обрезается с конца: инструкция и критерии на месте."""
        resume = self.p.read_resume()
        long = "Начало вакансии. " + "Требование. " * 4000 + "КОНЕЦ"
        prompt = self.p.analysis_prompt(resume, long)
        self.assertLessEqual(len(prompt), settings.prompt_room(settings.OPTIONS))
        self.assertIn("Начало вакансии.", prompt)
        self.assertIn(P.VACANCY_CUT.strip(), prompt)
        self.assertNotIn("КОНЕЦ", prompt)
        self.assertIn(self.p.read_criteria().strip()[:40], prompt)
        short = self.p.analysis_prompt(resume, "Короткая вакансия.")
        self.assertNotIn(P.VACANCY_CUT.strip(), short)

    def test_letter_drops_extras_first(self):
        """Письмо: не помещается — сначала уходит письмо, отправленное в компанию раньше, потом свои письма,
        и только потом обрезается вакансия."""
        resume, room = self.p.read_resume(), settings.prompt_room(settings.LETTER_OPTIONS)
        base = len(self.p.letter_prompt(resume, "", "- опыт"))
        vacancy = "Вакансия. " * ((room - base - 3000) // 10)          # помещается только без прежнего письма
        prompt = self.p.letter_prompt(resume, vacancy, "- опыт", samples=["Моё письмо."], earlier="ПРЕЖНЕЕ " * 600)
        self.assertNotIn("ПРЕЖНЕЕ", prompt)
        self.assertIn("Моё письмо.", prompt)
        self.assertNotIn(P.VACANCY_CUT.strip(), prompt)

    def test_resume_room(self):
        """Предел для мастера: резюме с «о себе» и критериями, рядом с которым влезает обычная вакансия."""
        room = setup.resume_room()
        self.assertGreater(room, 15000)
        self.assertLess(room, settings.prompt_room(settings.OPTIONS) - setup.VACANCY_ROOM)


if __name__ == "__main__":
    unittest.main()
