"""Запоминание текста файлов разбора: файл поменялся — читается заново."""
import tempfile
import unittest
from pathlib import Path

import helpers  # noqa: F401 — путь к проекту

from vacancy_assistant.files import cached_text, read_prop, set_prop
from vacancy_assistant.textio import write_text


class CachedText(unittest.TestCase):
    def test_change_is_seen(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "01 Вакансия.md"
            write_text(f, "---\nзаметка: старая\n---\n<!-- {} -->\n")
            self.assertEqual(read_prop(f, "заметка"), "старая")
            set_prop(f, "заметка", "новая, длиннее")              # и размер, и время изменения другие
            self.assertEqual(read_prop(f, "заметка"), "новая, длиннее")
            write_text(f, "---\nзаметка: ещё-1\n---\n<!-- {} -->\n")
            write_text(f, "---\nзаметка: ещё-2\n---\n<!-- {} -->\n")   # тот же размер — сразу следом
            self.assertIn("ещё-2", cached_text(f))


if __name__ == "__main__":
    unittest.main()
