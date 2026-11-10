"""Пробный запуск собранной программы: всё на месте — 0; нет папки окна или шаблона — ошибка, а не релиз."""
import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

import helpers  # noqa: F401 — журнал тестов во временной папке

from vacancy_assistant import app as A, selfcheck, settings


def run():
    lines = []
    with mock.patch.dict(os.environ), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        code = selfcheck.run(https=False, out=lines.append)
    return code, "\n".join(lines)


class SelfCheck(unittest.TestCase):
    def test_all_in_place(self):
        code, report = run()
        self.assertEqual(code, 0, report)
        self.assertIn("всё в порядке", report)

    def test_no_web_folder(self):
        with mock.patch.object(A, "WEB", Path(tempfile.mkdtemp())):
            code, report = run()
        self.assertEqual(code, 1)
        self.assertIn("страница окна", report)

    def test_no_template(self):
        with mock.patch.object(settings, "LETTER_TEMPLATE", settings.TEMPLATES / "нет такого.txt"):
            code, report = run()
        self.assertEqual(code, 1)
        self.assertIn("нет такого.txt", report)

    def test_data_root_untouched(self):
        """Пробный запуск — во временной папке: переменные окружения после него прежние."""
        before = os.environ.get("VACANCY_ASSISTANT_HOME")
        run()
        self.assertEqual(os.environ.get("VACANCY_ASSISTANT_HOME"), before)


if __name__ == "__main__":
    unittest.main()
