"""Номера вакансий после 99 (#58): 100, 101… — не «10», и вакансия 10 не путается с сотыми."""
import tempfile
import unittest
from pathlib import Path

from vacancy_assistant.files import numbered_files, save_numbered, vacancy_number


class Numbers(unittest.TestCase):
    def test_past_99(self):
        with tempfile.TemporaryDirectory() as d:
            for n in (1, 10, 98, 99):
                (Path(d) / f"{n:02d} Вакансия {n}.md").write_text("x")
            self.assertEqual(save_numbered(d, "Сотая", "x")[0], 100)
            self.assertEqual(save_numbered(d, "Сто первая", "x")[0], 101)
            files = numbered_files(d)
            self.assertEqual(sorted(files), [1, 10, 98, 99, 100, 101])
            self.assertEqual(files[10].name, "10 Вакансия 10.md")              # десятая — не сотая
            self.assertEqual(vacancy_number(files[101]), 101)
            (Path(d) / "заметки.md").write_text("x")                           # без номера — не вакансия
            self.assertEqual(len(numbered_files(d)), 6)


if __name__ == "__main__":
    unittest.main()
