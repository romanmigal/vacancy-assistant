"""Вкладка «Артефакты»: отправленные письма и резюме, приложенные файлы, заметки; удаление — в Корзину."""
import base64
import shutil
import unittest
import zipfile

from helpers import TempProfile, fake_model

from vacancy_assistant import analysis, app as A, artifacts, backup
from vacancy_assistant.errors import AssistantError
from vacancy_assistant.profile import Profile


class Artifacts(unittest.TestCase):
    def setUp(self):
        self.t = TempProfile().__enter__()
        self.t.add_vacancy(1, "ИТ-директор")
        self.app = A.App(self.t.profiles, fetch_page=lambda url: "", ask=fake_model,
                         check=lambda: {"ollama": True, "model_ok": True})
        self.trashed = []
        self.app.trash = lambda path: (self.trashed.append(path.name), shutil.rmtree(path) if path.is_dir() else path.unlink())
        analysis.full_analysis(self.p(), self.path(), ask=fake_model, log=lambda *_: None)
        self.result = self.p().results / self.path().name

    def tearDown(self):
        self.t.__exit__(None, None, None)

    def p(self):
        return Profile("example", self.t.profiles)

    def path(self):
        return next(self.p().vacancies.glob("01 *.md"))

    def post(self, path, **body):
        return self.app.handle("POST", path, {}, {"profile": "example", "n": 1, **body})

    def card(self):
        return self.app.handle("GET", "/api/vacancy", {"profile": ["example"], "n": ["1"]}, {})

    def test_sent_letter_becomes_artifact(self):
        analysis.write_letter(self.p(), self.result, ask=lambda *a: "Письмо работодателю.", log=lambda *_: None)
        self.post("/api/letter/sent", kind="cover", key="", date="2026-10-27")
        shelf = self.card()["artifacts"]
        self.assertEqual([(e["type"], e["date"], e["text"]) for e in shelf], [("cover", "2026-10-27", "Письмо работодателю.")])
        self.post("/api/letter/sent", kind="cover", key="", date="2026-10-26")       # поправили дату — та же копия
        self.assertEqual([e["date"] for e in self.card()["artifacts"]], ["2026-10-26"])
        self.post("/api/letter/sent", kind="cover", key="", date="")                 # сняли отметку — копия в Корзину
        self.assertEqual(self.card()["artifacts"], [])
        self.assertEqual(len(self.trashed), 1)

    def test_remove_artifact_unmarks_version(self):
        analysis.save_text(self.p(), self.result, "resume", "Обо мне: руководитель ИТ.", "own")
        self.post("/api/letter/sent", kind="resume", key="", date="2026-10-28")
        aid = self.card()["artifacts"][0]["id"]
        self.post("/api/artifacts/remove", id=aid)
        card = self.card()
        self.assertEqual(card["artifacts"], [])
        self.assertNotIn("sent", card["resume_fits"][0])

    def test_file_and_note(self):
        pdf = b"%PDF-1.4 test"
        self.post("/api/artifacts/add", do="file", name="тестовое/задание.pdf", data=base64.b64encode(pdf).decode())
        self.post("/api/artifacts/add", do="note", title="Ответ HR в Telegram", text="Ждут до пятницы.", date="2026-10-28")
        card = self.card()
        files = [e for e in card["artifacts"] if e["type"] == "file"]
        self.assertEqual((files[0]["file"], files[0]["size"]), ("задание.pdf", len(pdf)))
        self.assertEqual((artifacts.folder(self.p(), self.result) / "задание.pdf").read_bytes(), pdf)
        self.assertEqual({(e["source"], e["title"]) for e in card["texts"]},
                         {("artifact", "задание.pdf"), ("artifact", "Ответ HR в Telegram")})
        rows = A.vacancy_rows(self.p())
        self.assertEqual(rows[0]["artifacts"], 2)
        with zipfile.ZipFile(backup.make(self.p())) as z:                           # файлы — в резервной копии
            self.assertTrue(any(n.endswith("артефакты/" + self.result.stem + "/задание.pdf") for n in z.namelist()))

    def test_limits(self):
        with self.assertRaises(AssistantError):
            artifacts.add_file(self.p(), self.result, "big.bin", b"x" * (artifacts.MAX_FILE + 1))
        with self.assertRaises(AssistantError):
            artifacts.add_text(self.p(), self.result, "note", "Пусто", "  ")


if __name__ == "__main__":
    unittest.main()
