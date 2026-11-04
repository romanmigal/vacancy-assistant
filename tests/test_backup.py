"""Резервные копии профиля: архив, восстановление новым профилем и вместо текущего, автокопия, Корзина."""
import base64
import io
import json
import unittest
import zipfile
from datetime import datetime, timedelta

from helpers import TempProfile

from vacancy_assistant import app as A, backup
from vacancy_assistant.errors import AssistantError
from vacancy_assistant.profile import Profile
from vacancy_assistant.textio import read_json, read_text, write_json, write_text


def files(folder):
    return sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file())


class Backup(unittest.TestCase):
    def setUp(self):
        self.t = TempProfile().__enter__()
        self.bin = self.t.tmp / "Корзина"
        self.bin.mkdir()
        self.t.add_vacancy(1, "Директор по ИТ")
        write_json(self.t.tmp / "профили" / "облако.json", {"auth_key": "СЕКРЕТ"})     # ключ — вне профиля

    def tearDown(self):
        self.t.__exit__(None, None, None)

    def trash(self, path):
        path.rename(self.bin / path.name)

    def test_copy_and_restore_as_new(self):
        path = backup.make(self.t.profile)
        self.assertEqual(path.parent, self.t.tmp / "копии")
        with zipfile.ZipFile(path) as z:
            self.assertNotIn("СЕКРЕТ", "".join(z.read(n).decode("utf-8", "ignore") for n in z.namelist()))
            self.assertEqual(json.loads(z.read("копия.json"))["профиль"], "example")
        name = backup.restore(self.t.profiles, path)
        self.assertEqual(name, "example-восстановлен")
        self.assertEqual(files(self.t.profiles / name), files(self.t.profile.dir))
        self.assertEqual(backup.restore(self.t.profiles, path), "example-восстановлен-2")
        self.assertEqual(backup.listing(self.t.profiles)[0]["file"], path.name)

    def test_restore_replaces_current(self):
        path = backup.make(self.t.profile)
        write_text(self.t.profile.criteria_file, "изменено после копии")
        self.assertEqual(backup.restore(self.t.profiles, path, into=self.t.profile, trash=self.trash), "example")
        self.assertNotEqual(read_text(self.t.profile.criteria_file), "изменено после копии")
        self.assertEqual(read_text(self.bin / "example" / "критерии.txt"), "изменено после копии")   # прежняя — в Корзине
        self.assertEqual(len(backup.listing(self.t.profiles)), 2)                  # и сохранена в копию

    def test_move_to_another_computer(self):
        """Экспорт → другой компьютер (своя папка профилей): прежнее имя, если свободно, иначе своё или предложенное."""
        path = backup.make(self.t.profile)
        other = self.t.tmp / "другой компьютер" / "профили"
        other.mkdir(parents=True)
        info = backup.inspect(other, path)
        self.assertEqual((info["profile"], info["suggested"], info["cloud"]), ("example", "example", False))
        self.assertEqual(backup.restore(other, path), "example")
        self.assertEqual(files(other / "example"), files(self.t.profile.dir))
        self.assertEqual(backup.inspect(other, path)["suggested"], "example-восстановлен")     # занято — другое
        for bad in ("example", "с пробелом", "../x"):
            with self.assertRaises(AssistantError):
                backup.restore(other, path, name=bad)
        self.assertEqual(backup.restore(other, path, name="maria"), "maria")
        self.assertFalse((other.parent / "копии").exists())                     # на новом компьютере копий не делаем

    def test_inspect_shows_cloud_model(self):
        config = read_json(self.t.profile.dir / "профиль.json")
        write_json(self.t.profile.dir / "профиль.json", {**config, "модель": {"облако": True}})
        self.assertTrue(backup.inspect(self.t.profiles, backup.make(self.t.profile))["cloud"])

    def test_vault_path_follows_new_name(self):
        config = read_json(self.t.profile.dir / "профиль.json")
        write_json(self.t.profile.dir / "профиль.json", {**config, "путь_в_obsidian": "ai-project/профили/example"})
        name = backup.restore(self.t.profiles, backup.make(self.t.profile))
        self.assertEqual(Profile(name, self.t.profiles).vault_prefix, "ai-project/профили/example-восстановлен")

    def test_bad_archives(self):
        def archive(entries):
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as z:
                for n, data in entries.items():
                    z.writestr(n, data)
            buf.seek(0)
            return buf
        manifest = json.dumps({"профиль": "x", "версия": "0.1"})
        for bad in (io.BytesIO(b"not a zip"), archive({"x/профиль.json": "{}"}), archive({"копия.json": manifest}),
                    archive({"копия.json": manifest, "x/профиль.json": "{}", "x/../../evil.txt": "!"}),
                    archive({"копия.json": json.dumps({"профиль": "x", "версия": "99.0"}), "x/профиль.json": "{}"})):
            with self.assertRaises(AssistantError):
                backup.restore(self.t.profiles, bad)
        self.assertFalse((self.t.tmp / "evil.txt").exists())

    def test_auto_weekly_keeps_four(self):
        start = datetime(2026, 1, 1, 9, 0)
        for week in range(6):
            backup.auto(self.t.profiles, now=start + timedelta(days=7 * week), trash=self.trash, log=lambda *_: None)
            backup.auto(self.t.profiles, now=start + timedelta(days=7 * week, hours=1), trash=self.trash, log=lambda *_: None)
        autos = [c for c in backup.listing(self.t.profiles) if c["auto"]]
        self.assertEqual([c["created"][:10] for c in autos], ["2026-02-05", "2026-01-29", "2026-01-22", "2026-01-15"])
        self.assertEqual(len(list(self.bin.glob("*.zip"))), 2)                     # старые — в Корзине, не удалены
        backup.make(self.t.profile)                                                 # свои копии автокопия не трогает
        backup.auto(self.t.profiles, now=start + timedelta(days=60), trash=self.trash, log=lambda *_: None)
        self.assertEqual(len([c for c in backup.listing(self.t.profiles) if not c["auto"]]), 1)


class BackupApi(unittest.TestCase):
    def setUp(self):
        self.t = TempProfile().__enter__()
        self.app = A.App(self.t.profiles)
        self.bin = self.t.tmp / "Корзина"
        self.bin.mkdir()
        self.app.trash = lambda path: path.rename(self.bin / path.name)

    def tearDown(self):
        self.t.__exit__(None, None, None)

    def call(self, path, body):
        try:
            return 200, self.app.handle("POST", path, {}, body)
        except AssistantError as e:
            return 400, {"error": str(e)}

    def test_save_list_restore(self):
        status, r = self.call("/api/backup/save", {"profile": "example"})
        self.assertEqual(status, 200)
        self.assertEqual([c["file"] for c in r["copies"]], [r["file"]])
        status, r = self.call("/api/backup/restore", {"file": r["file"], "profile": "example"})
        self.assertEqual((status, r["profile"]), (200, "example-восстановлен"))
        data = base64.b64encode((self.t.tmp / "копии" / r["copies"][0]["file"]).read_bytes()).decode()
        self.assertEqual(self.call("/api/backup/restore", {"data": data})[1]["profile"], "example-восстановлен-2")
        status, r = self.call("/api/backup/restore", {"file": r["copies"][0]["file"], "profile": "example", "replace": True})
        self.assertEqual((status, r["profile"]), (200, "example"))
        self.assertTrue((self.bin / "example").is_dir())
        self.assertEqual(self.call("/api/backup/restore", {"file": "../профили/example/профиль.json"})[0], 400)

    def test_export_and_import(self):
        status, r = self.call("/api/backup/export", {"profile": "example"})
        self.assertEqual(status, 200)
        self.assertEqual(base64.b64decode(r["data"]), (self.t.tmp / "копии" / r["file"]).read_bytes())
        status, info = self.call("/api/backup/inspect", {"data": r["data"]})
        self.assertEqual((status, info["suggested"], info["has_key"]), (200, "example-восстановлен", False))
        self.assertEqual(self.call("/api/backup/restore", {"data": r["data"], "name": "ivan"})[1]["profile"], "ivan")
        self.assertEqual(self.call("/api/backup/restore", {"data": r["data"], "name": "ivan"})[0], 400)   # имя занято

    def test_remote_forbidden(self):
        for path in ("/api/backup/save", "/api/backup/export", "/api/backup/inspect", "/api/backup/restore", "/api/backup/show"):
            with self.assertRaises(A.Forbidden):
                self.app.handle("POST", path, {}, {"profile": "example"}, remote=True)


if __name__ == "__main__":
    unittest.main()
