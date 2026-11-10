"""Режим «Без модели»: действия с моделью отказывают, вакансии сохраняются без разбора, а этап,
комментарий и актуальность работают; включили модель — сохранённые без разбора разбираются."""
import unittest

from helpers import TempProfile, fake_model

from vacancy_assistant import analysis, app as A, funnel, setup, stats, summary, vacancies as V, work as W
from vacancy_assistant.errors import AssistantError
from vacancy_assistant.files import read_meta, set_prop
from vacancy_assistant.profile import Profile
from vacancy_assistant.textio import read_text

TEXT = ("Руководитель ИТ-направления\n\nКомпания: ООО Пример\n\nОбязанности: развитие ИТ, управление командой "
        "из 20 человек, бюджет, подрядчики. Требования: опыт руководства ИТ от 5 лет.")


def no_ask(*a, **k):
    raise AssertionError("в режиме без модели модель не вызывается")


class NoModel(unittest.TestCase):
    def setUp(self):
        self.t = TempProfile().__enter__()
        self.p().set_model(False, off=True)

    def tearDown(self):
        self.t.__exit__(None, None, None)

    def p(self):
        return Profile("example", self.t.profiles)

    def add(self):
        _, work = W.make_work(self.p(), "add_text", {"text": TEXT, "link": "https://example.ru/job/1"}, ask=no_ask)
        work(lambda *_: None)
        return V.vacancy_rows(self.p())[0]

    def test_mode(self):
        p = self.p()
        self.assertTrue(p.no_model)
        self.assertFalse(p.use_cloud)
        self.assertFalse(p.llm_pages)                                  # страницы — целиком, без модели
        state = A.App(self.t.profiles, ask=no_ask).handle("GET", "/api/state", {"profile": ["example"]}, {})
        self.assertTrue(state["no_model"])
        self.assertEqual(state["model"], "не используется")

    def test_wizard_choice(self):
        from test_setup import ANSWERS
        self.assertEqual(setup.build_config({**ANSWERS, "no_model": True})["модель"], {"облако": False, "без_модели": True})
        self.assertEqual(setup.build_config(ANSWERS)["модель"], {"облако": False})

    def test_edit_profile_model_step(self):
        """Шаг «Модель» в «Редактировать профиль»: выбор читается из профиля и сохраняется."""
        p = self.p()
        self.assertEqual(setup.answers_from_profile(p)["model_pick"], "none")
        r = setup.update_profile(p, {"model_pick": "local"}, log=lambda *_: None)
        self.assertIn("модель", r["changed"])
        self.assertFalse(self.p().no_model)
        with self.assertRaises(AssistantError):                    # облачная — только с подключённым ключом
            setup.update_profile(self.p(), {"model_pick": "cloud"}, log=lambda *_: None)
        self.assertEqual(setup.update_profile(self.p(), {"model_pick": "local"}, log=lambda *_: None)["changed"], [])

    def test_model_actions_refused(self):
        self.t.add_vacancy(1, "ИТ-директор")
        for action in sorted(W.NEEDS_MODEL):
            with self.assertRaises(AssistantError, msg=action) as e:
                W.make_work(self.p(), action, {"n": 1, "reanalyze": ["new"], "statuses": ["new"]}, ask=no_ask)
            self.assertIn("Нужна модель", str(e.exception))

    def test_saved_without_analysis(self):
        row = self.add()
        self.assertEqual((row["stage"], row["score"], row["decision"]), ("none", None, ""))
        self.assertTrue(row["analyzed"])                                   # «пустой разбор» — есть куда писать этап
        result = next(self.p().results.glob("01 *.md"))
        funnel.set_stage(result, "applied")
        set_prop(result, "заметка", "написал HR")
        row = V.vacancy_rows(self.p())[0]
        self.assertEqual((row["funnel"]["stage"], row["note"]), ("applied", "написал HR"))
        self.assertEqual(stats.compute([row])["totals"]["analyzed"]["total"], 0)   # «Разобрано ИИ» — нет
        self.assertEqual(stats.compute([row])["totals"]["applied"]["total"], 1)
        self.assertFalse(row["criteria_changed"])                           # не просит «Пересчитать оценки»
        self.assertEqual(funnel.read_analyses(self.p(), result), [])        # в историю разборов не попадает
        summary.write_summary(self.p(), lambda *_: None)
        self.assertIn("без разбора", read_text(self.p().dir / "Сводка.md"))

    def test_refresh_card_checks_only(self):
        self.add()
        _, work = W.make_work(self.p(), "refresh_card", {"n": 1}, fetch_page=lambda url: TEXT, ask=no_ask)
        work(lambda *_: None)
        result = next(self.p().results.glob("01 *.md"))
        self.assertEqual(read_meta(result)["stage"], "none")                # разбора не было

    def test_model_back_analyzes_saved(self):
        self.add()
        result = next(self.p().results.glob("01 *.md"))
        funnel.set_stage(result, "applied")
        self.p().set_model(False)
        p = self.p()
        self.assertFalse(p.no_model)
        _, work = W.make_work(p, "analyze", {}, ask=fake_model)
        work(lambda *_: None)
        meta = read_meta(result)
        self.assertNotEqual(meta["stage"], "none")
        self.assertIsNotNone(meta["score"])
        self.assertEqual(funnel.read(result)["stage"], "applied")            # этап пережил разбор

    def test_letter_after_model_on_analyzes_first(self):
        self.add()
        self.p().set_model(False)
        prompts = []
        _, work = W.make_work(self.p(), "letter", {"n": 1}, ask=lambda prompt, *a: prompts.append(prompt) or fake_model(prompt))
        work(lambda *_: None)
        self.assertGreaterEqual(len(prompts), 2)                             # сначала разбор, потом письмо
        self.assertTrue((self.p().letters / next(self.p().results.glob("01 *.md")).name).exists())


if __name__ == "__main__":
    unittest.main()
