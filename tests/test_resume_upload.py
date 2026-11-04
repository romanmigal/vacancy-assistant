"""Новое резюме из файла, когда профиль берёт резюме из файла вне своей папки: ложится в папку профиля,
внешний файл не меняется."""
import unittest

from helpers import TempProfile

from vacancy_assistant import setup
from vacancy_assistant.profile import Profile
from vacancy_assistant.textio import read_text, write_text


class ResumeUpload(unittest.TestCase):
    def test_external_resume_replaced(self):
        with TempProfile() as t:
            outside = t.profiles / "моё резюме.md"
            write_text(outside, "# Старое резюме\n")
            p = Profile("example", t.profiles)
            p.config["резюме"] = "../моё резюме.md"
            p.save_config()
            p = Profile("example", t.profiles)
            self.assertFalse(setup.answers_from_profile(p)["resume_editable"])
            res = setup.update_profile(p, {"resume": "# Новое резюме"}, log=lambda *_: None)   # без загрузки — не пишем
            self.assertNotIn("резюме", " ".join(res["changed"]))
            res = setup.update_profile(Profile("example", t.profiles), {"resume": "# Новое резюме", "resume_to_profile": True},
                                       log=lambda *_: None)
            self.assertIn("резюме (теперь в папке профиля)", res["changed"])
            p = Profile("example", t.profiles)
            self.assertEqual(p.read_resume(), "# Новое резюме\n")
            self.assertEqual(p.resume, (p.dir / "резюме.md").resolve())
            self.assertEqual(read_text(outside), "# Старое резюме\n")                  # внешний файл как был
            self.assertTrue(setup.answers_from_profile(p)["resume_editable"])


if __name__ == "__main__":
    unittest.main()
