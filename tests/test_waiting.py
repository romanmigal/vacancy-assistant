"""Ожидание ответа модели: «Остановить» срабатывает, пока модель думает; предел времени; строки «жду ответа…»."""
import threading
import unittest
from unittest import mock

from vacancy_assistant import waiting
from vacancy_assistant.errors import AssistantError
from vacancy_assistant.tasks import Stopped


class Waiting(unittest.TestCase):
    def setUp(self):
        for name, value in (("STEP", 0.01), ("LOG_EVERY", 0.05)):
            p = mock.patch.object(waiting, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(waiting.on_wait, None)
        self.release = threading.Event()
        self.addCleanup(self.release.set)            # брошенный «запрос» не висит после теста

    def slow(self):
        self.release.wait(5)
        return "ответ"

    def test_answer_and_error_pass_through(self):
        self.assertEqual(waiting.run(lambda: "ок", "GigaChat", 5, AssistantError("долго")), "ок")
        with self.assertRaises(ValueError):
            waiting.run(lambda: (_ for _ in ()).throw(ValueError("сеть")), "GigaChat", 5, AssistantError("долго"))

    def test_limit(self):
        with self.assertRaises(AssistantError) as e:
            waiting.run(self.slow, "GigaChat", 0.1, AssistantError("GigaChat не ответил"))
        self.assertIn("не ответил", str(e.exception))

    def test_stop_while_waiting(self):
        lines, stop = [], {"now": False}

        def hook(message):
            if message:
                lines.append(message)
                stop["now"] = True                   # нажали «Остановить», пока модель думает
            elif stop["now"]:
                raise Stopped("Остановлено")
        waiting.on_wait(hook)
        with self.assertRaises(Stopped):
            waiting.run(self.slow, "GigaChat", 5, AssistantError("долго"))
        self.assertTrue(lines[0].strip().startswith("жду ответа GigaChat"))


if __name__ == "__main__":
    unittest.main()
