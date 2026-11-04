"""Папка с данными: проверка выбранной папки, переход на неё, профили в ней подхватываются."""
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from helpers import TempProfile

from vacancy_assistant import app as A, datadir, settings
from vacancy_assistant.errors import AssistantError


class DataDir(unittest.TestCase):
    def setUp(self):
        self.t = TempProfile().__enter__()
        self.other = Path(tempfile.mkdtemp())
        self.app = A.App(self.t.profiles)

    def tearDown(self):
        self.t.__exit__(None, None, None)
        shutil.rmtree(self.other, ignore_errors=True)

    def call(self, path, body=None):
        return self.app.handle("POST" if body is not None else "GET", path, {}, body or {})

    def test_inspect(self):
        self.assertIn("нет", datadir.inspect(self.other / "нет такой")["problem"])
        self.assertIn("полный путь", datadir.inspect("относительно")["problem"])
        self.assertEqual(datadir.inspect(self.other), {"home": str(self.other), "profiles": [], "problem": ""})
        shutil.copytree(self.t.profile.dir, self.other / "профили" / "anna")
        self.assertEqual(datadir.inspect(self.other)["profiles"], ["anna"])
        self.assertEqual(datadir.inspect(self.other / "профили")["home"], str(self.other))   # выбрали саму «профили»
        loose = Path(tempfile.mkdtemp())
        try:
            shutil.copytree(self.t.profile.dir, loose / "anna")                               # профили без «профили/»
            self.assertIn("«профили»", datadir.inspect(loose)["problem"])
        finally:
            shutil.rmtree(loose)

    def test_switch_picks_up_profiles(self):
        shutil.copytree(self.t.profile.dir, self.other / "профили" / "anna")
        r = self.call("/api/datadir/set", {"path": str(self.other)})
        self.assertEqual((r["home"], r["profiles"]), (str(self.other), ["anna"]))
        self.assertEqual(self.call("/api/state")["profile"], "anna")
        self.assertTrue(self.t.profile.dir.exists())                                 # прежняя папка не тронута

    def test_switch_to_empty(self):
        r = self.call("/api/datadir/set", {"path": str(self.other)})
        self.assertEqual(r["profiles"], [])
        self.assertTrue((self.other / "профили").is_dir())
        self.assertEqual(self.call("/api/state")["profiles"], [])                    # окно откроет мастер

    def test_bad_path_and_pick(self):
        with self.assertRaises(AssistantError):
            self.call("/api/datadir/set", {"path": str(self.other / "нет")})
        self.app.pick_folder = lambda: None
        self.assertEqual(self.call("/api/datadir/pick", {}), {"picked": False})
        self.app.pick_folder = lambda: str(self.other)
        self.assertEqual(self.call("/api/datadir/pick", {})["home"], str(self.other))

    def test_remembered_folder(self):
        """Выбор запоминается вне папки данных; явная VACANCY_ASSISTANT_HOME — важнее."""
        old = os.environ.pop("VACANCY_ASSISTANT_HOME", None)
        try:
            datadir.remember(self.other)
            self.assertEqual(datadir.saved(), self.other)
            self.assertEqual(settings.data_root(), self.other)
            os.environ["VACANCY_ASSISTANT_HOME"] = str(self.t.tmp)
            self.assertEqual(settings.data_root(), Path(self.t.tmp))
        finally:
            (datadir.config_dir() / datadir.POINTER).unlink(missing_ok=True)
            os.environ.pop("VACANCY_ASSISTANT_HOME", None)
            if old is not None:
                os.environ["VACANCY_ASSISTANT_HOME"] = old


if __name__ == "__main__":
    unittest.main()
