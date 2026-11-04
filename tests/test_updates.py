"""Проверка обновлений: сравнение версий, раз в день, выключатель, недоступный адрес — тихо."""
import os
import shutil
import subprocess
import unittest
from datetime import date
from pathlib import Path

from helpers import TempProfile

from vacancy_assistant import app as A, updates as U

LATEST = {"version": "0.10.0", "url": "https://github.com/romanmigal/job-search-assistant-releases/releases/tag/v0.10.0",
          "notes": "Окно «Зарплаты»"}


class Versions(unittest.TestCase):
    def test_compare(self):
        self.assertTrue(U.newer("0.10.0", "0.4.0"))              # не строками: 0.10 > 0.4
        self.assertTrue(U.newer("v0.4.1", "0.4.0"))
        self.assertTrue(U.newer("1.0", "0.9.9"))
        self.assertFalse(U.newer("0.4.0", "0.4.0"))
        self.assertFalse(U.newer("0.4", "0.4.0"))
        self.assertFalse(U.newer("0.3.9", "0.4.0"))
        self.assertFalse(U.newer("новая", "0.4.0"))

    def test_clean(self):
        self.assertIsNone(U.clean({"version": "x"}))
        self.assertIsNone(U.clean(["0.5.0"]))
        bad = U.clean({"version": "0.5.0", "url": "javascript:alert(1)"})
        self.assertTrue(bad["url"].startswith("https://"))


class Notes(unittest.TestCase):
    def test_section(self):
        text = "# Что нового\n\n## 0.10.0 (готовится)\n\n- новое\n\n## 0.1.0 — 01.10.2026\n\n- старое\n"
        self.assertEqual(U.release_notes("v0.10.0", text), "- новое")
        self.assertEqual(U.release_notes("0.1.0", text), "- старое")
        self.assertEqual(U.release_notes("0.1", text), "")                     # «0.1» — не «0.10.0» и не «0.1.0»

    def test_current_version_described(self):
        """Перед релизом в «Что нового» должен быть раздел текущей версии — он пойдёт в описание релиза."""
        from vacancy_assistant import __version__
        self.assertTrue(U.release_notes(__version__))


class State(unittest.TestCase):
    def setUp(self):
        self.t = TempProfile().__enter__()
        self.folder = Path(self.t.profiles)
        self.calls = []

    def tearDown(self):
        self.t.__exit__(None, None, None)

    def fetch(self):
        self.calls.append(1)
        return LATEST

    def test_once_a_day(self):
        day = date(2026, 10, 29)
        s = U.state(self.folder, self.fetch, day, current="0.4.0")
        self.assertTrue(s["newer"])
        self.assertEqual(s["latest"]["version"], "0.10.0")
        U.state(self.folder, self.fetch, day, current="0.4.0")
        self.assertEqual(len(self.calls), 1)                    # второй раз за день — без запроса
        U.state(self.folder, self.fetch, date(2026, 10, 30), current="0.4.0")
        self.assertEqual(len(self.calls), 2)

    def test_unreachable_is_quiet(self):
        def down():
            raise OSError("нет сети")
        s = U.state(self.folder, down, date(2026, 10, 29), current="0.4.0")
        self.assertEqual((s["newer"], s["latest"]), (False, None))

    def test_disabled_no_request(self):
        U.set_enabled(self.folder, False)
        s = U.state(self.folder, lambda: self.fail("проверка выключена"), date(2026, 10, 29))
        self.assertEqual((s["enabled"], s["newer"]), (False, False))

    def test_check_now(self):
        """Кнопка «Проверить обновления»: запрос сразу, даже если сегодня проверяли и если автоматическая выключена."""
        day = date(2026, 10, 29)
        U.state(self.folder, self.fetch, day, current="0.4.0")
        s = U.state(self.folder, self.fetch, day, current="0.4.0", force=True)
        self.assertEqual((len(self.calls), s["newer"], s["problem"]), (2, True, ""))
        U.set_enabled(self.folder, False)
        s = U.state(self.folder, self.fetch, day, current="0.10.0", force=True)
        self.assertEqual((len(self.calls), s["newer"], s["latest"]["version"]), (3, False, "0.10.0"))

    def test_check_now_offline(self):
        """Нет сети — понятное сообщение, прежний ответ остаётся."""
        day = date(2026, 10, 29)
        U.state(self.folder, self.fetch, day, current="0.4.0")
        def down():
            raise OSError("нет сети")
        s = U.state(self.folder, down, day, current="0.4.0", force=True)
        self.assertIn("нет связи", s["problem"])
        self.assertEqual(U.load(self.folder)["latest"]["version"], "0.10.0")
        self.assertIn("непонятно", U.state(self.folder, lambda: {"x": 1}, day, force=True)["problem"])

    def test_route(self):
        app = A.App(self.t.profiles)
        app.fetch_latest = self.fetch
        self.assertTrue(app.handle("GET", "/api/updates", {}, {})["enabled"])
        self.assertFalse(app.handle("POST", "/api/updates", {}, {"enabled": False})["enabled"])
        self.assertFalse(U.load(self.folder)["enabled"])
        self.assertTrue(app.handle("POST", "/api/updates", {}, {"check": True})["newer"])     # при выключенной — тоже


class MacInstall(unittest.TestCase):
    """Команда установки на Mac: скрипт на месте и разбирается bash, во всех инструкциях — одна и та же строка."""
    ROOT = Path(__file__).resolve().parent.parent

    def test_script(self):
        from vacancy_assistant import settings
        script = self.ROOT / "packaging/install_mac.sh"
        self.assertIn("/main/packaging/install_mac.sh", settings.MAC_INSTALL)
        if shutil.which("bash") and os.name != "nt":
            self.assertEqual(subprocess.run(["bash", "-n", str(script)]).returncode, 0)
        for doc in ("README.md", "packaging/releases-README.md", "packaging/Как установить на Mac.txt"):
            self.assertIn(settings.MAC_INSTALL, (self.ROOT / doc).read_text(encoding="utf-8"), doc)


if __name__ == "__main__":
    unittest.main()
