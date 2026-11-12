"""Мастер первого запуска: профиль из анкеты и адреса мастера в окне программы."""
import json
import unittest

from helpers import TempProfile, fake_model

from vacancy_assistant import analysis, setup
from vacancy_assistant.profile import Profile, default_profile_name
from vacancy_assistant.textio import read_text

ANSWERS = {"name": "Мария Иванова", "female": True, "field": "финансы", "start": "сразу",
           "resume": "# Резюме\n\nГлавный бухгалтер, 12 лет.", "titles": "Главный бухгалтер\nФинансовый директор",
           "city": "Санкт-Петербург", "office": True, "hybrid": True, "remote": True, "salary": "250 000",
           "part_time": True, "important": "производство\nкрупная компания", "not_ok": "постоянные командировки",
           "stop_words": "стажёр\nпомощник"}


class Setup(unittest.TestCase):
    def test_pull_model_shows_progress_of_whole_model(self):
        import io
        import json
        from unittest import mock
        GB = 2**30
        events = [{"status": "pulling manifest"},
                  {"status": "pulling aa", "digest": "sha256:aa", "total": 1000, "completed": 1000}]   # маленькая — сразу 100%
        events += [{"status": "pulling bb", "digest": "sha256:bb", "total": 8 * GB, "completed": k * GB} for k in range(9)]
        events += [{"status": "verifying sha256 digest"}, {"status": "success"}]
        body = io.BytesIO("".join(json.dumps(e) + "\n" for e in events).encode())
        body.__enter__ = lambda *a: body
        body.__exit__ = lambda *a: None
        ticks = iter(range(0, 1000, 20))                              # каждое событие — через 20 «секунд»
        lines = []
        with mock.patch.object(setup.urllib.request, "urlopen", lambda *a, **k: body):
            setup.pull_model(log=lines.append, clock=lambda: next(ticks))
        progress = [l for l in lines if "ГБ" in l]
        self.assertTrue(any(l.startswith("50%") for l in progress), progress)        # большую часть видно
        self.assertTrue(progress[-1].startswith("100% — 8.0 из 8.0 ГБ"), progress)
        self.assertTrue(any("МБ/с" in l for l in progress))                            # скорость
        self.assertIn("Проверяю скачанное — это может занять пару минут…", lines)

    def test_check_computer_runs(self):
        c = setup.check_computer()                       # без моков: не падает на этой системе
        self.assertIsInstance(c["ollama_installed"], bool)
        self.assertTrue(c["ollama_installed"] or not c["ollama"])     # запущена — значит, установлена

    def test_profile_id(self):
        self.assertEqual(setup.profile_id("Мария Иванова"), "mariya")
        self.assertEqual(setup.profile_id("Мария", {"mariya", "mariya2"}), "mariya3")
        self.assertEqual(setup.profile_id("Юлия"), "yuliya")

    def test_criteria(self):
        c = setup.build_criteria(ANSWERS)
        self.assertIn("К1. Локация и формат: Санкт-Петербург (офис или гибрид) или удалённо из любого города.", c)
        self.assertIn("от 250 000 ₽ в месяц", c)
        self.assertIn("Временная или проектная роль", c)                       # частичная занятость
        self.assertIn("К3. Должность: подходят роли «Главный бухгалтер», «Финансовый директор»", c)
        self.assertIn("К4. Не подходит: постоянные командировки.", c)
        self.assertIn("+ производство;\n+ крупная компания.", c)
        no_salary = setup.build_criteria({**ANSWERS, "salary": "", "not_ok": ""})
        self.assertNotIn("Зарплата", no_salary)
        self.assertIn("К2. Должность", no_salary)

    def test_create_profile(self):
        with TempProfile() as t:
            name = setup.create_profile(ANSWERS, t.profiles, log=lambda *_: None)
            self.assertEqual(name, "mariya")
            self.assertEqual(default_profile_name(t.profiles), "mariya")       # первый настоящий — по умолчанию
            p = Profile(name, t.profiles)
            self.assertEqual(p.search_where, [("Санкт-Петербург", "area=2"), ("удалённо", "area=113&work_format=REMOTE")])
            self.assertEqual(read_text(p.searches).splitlines()[-2:], ["Главный бухгалтер", "Финансовый директор"])
            self.assertIn("Буду рада обсудить детали.", read_text(p.letter_example))
            self.assertIn("решала", read_text(p.letter_example))
            # отсев по названию: слово из должностей есть, стоп-слова нет; уровень не проверяем
            self.assertTrue(p.title_fits("Главного бухгалтера в холдинг"))
            self.assertTrue(p.title_fits("Заместитель финансового директора"))
            self.assertFalse(p.title_fits("Помощник бухгалтера"))
            self.assertFalse(p.title_fits("Менеджер по продажам"))
            self.assertFalse(p.title_fits("Бухгалтер по расчёту зарплаты"))         # уровень ниже: нет «главн»/«директ»
            self.assertTrue(p.title_fits("Директор по финансам"))
            config = json.loads(read_text(p.dir / "профиль.json"))
            self.assertIn("финансы", config["разбор"]["для_кого"])
            # профиль рабочий: разбор и письмо проходят
            t.profile = p
            t.add_vacancy(1, "Главный бухгалтер")
            analysis.analyze(p, log=lambda *_: None, ask=fake_model)
            self.assertEqual(len(analysis.write_letters(p, log=lambda *_: None, ask=fake_model)), 1)
            # второй профиль с тем же именем — другая папка, профиль по умолчанию не меняется
            self.assertEqual(setup.create_profile(ANSWERS, t.profiles, log=lambda *_: None), "mariya2")
            self.assertEqual(default_profile_name(t.profiles), "mariya")
            # имя профиля из мастера — как задано; занятое или с пробелами — ошибка
            self.assertEqual(setup.create_profile({**ANSWERS, "profile_id": "masha"}, t.profiles, log=lambda *_: None), "masha")
            for bad in ("masha", "маша иванова"):
                with self.assertRaises(setup.AssistantError):
                    setup.create_profile({**ANSWERS, "profile_id": bad}, t.profiles, log=lambda *_: None)

    def test_hide_past_employers_from_wizard(self):
        """Шаг «Резюме» с GigaChat: галочка «скрывать прошлых работодателей» — в профиль и обратно в мастер."""
        from vacancy_assistant import mask
        resume = "**ООО «Пример Ритейл» (Москва)** · ИТ-директор · 2021 — 2026\n"
        with TempProfile() as t:
            from vacancy_assistant.app import App
            body = App(t.profiles).handle("POST", "/api/setup/employers", {}, {"resume": resume})
            self.assertEqual(body["past"], ["ООО «Пример Ритейл»"])
            hidden = Profile(setup.create_profile({**ANSWERS, "cloud": True, "hide_firms": True}, t.profiles, log=lambda *_: None), t.profiles)
            self.assertTrue(mask.hide_companies(hidden))
            self.assertTrue(setup.answers_from_profile(hidden)["hide_firms"])
            local = Profile(setup.create_profile({**ANSWERS, "hide_firms": True}, t.profiles, log=lambda *_: None), t.profiles)
            self.assertFalse(mask.hide_companies(local))                       # без GigaChat скрывать не от кого
            changed = setup.update_profile(hidden, {"hide_firms": False}, log=lambda *_: None)["changed"]
            self.assertEqual(changed, ["скрытие прошлых работодателей"])
            self.assertFalse(mask.hide_companies(Profile(hidden.name, t.profiles)))

    def test_edit_profile_changes_only_what_changed(self):
        with TempProfile() as t:
            p = t.profile                                           # профиль-пример создан вручную, не мастером
            criteria, config_before = read_text(p.criteria_file), read_text(p.dir / "профиль.json")
            a = setup.answers_from_profile(p)
            self.assertEqual((a["name"], a["city"], a["remote"]), ("Иван Петров", "Москва", True))
            self.assertIn("информацион", a["title_words"])
            self.assertEqual(setup.update_profile(p, a, log=lambda *_: None)["changed"], [])   # ничего не меняли
            self.assertEqual(read_text(p.dir / "профиль.json"), config_before)
            changed = setup.update_profile(p, {**a, "name": "Иван Сидоров", "titles": "CIO\nCDO",
                                               "salary": "900 000"}, log=lambda *_: None)["changed"]
            self.assertEqual(changed, ["имя", "поисковые запросы"])                   # зарплата — только в анкету
            p = Profile("example", t.profiles)
            self.assertEqual((p.display_name, p.config["письмо"]["подпись"]), ("Иван Сидоров", "Иван Сидоров"))
            self.assertEqual(read_text(p.criteria_file), criteria)                     # критерии не тронуты
            self.assertTrue(read_text(p.searches).startswith("# Поисковые"))           # комментарии сохранены
            self.assertEqual(read_text(p.searches).splitlines()[-2:], ["CIO", "CDO"])
            self.assertEqual(setup.answers_from_profile(p)["salary"], "900 000")
            # переименование: папка, путь для Obsidian, профиль по умолчанию
            (t.profiles / "по_умолчанию.txt").write_text("example\n", encoding="utf-8")
            with self.assertRaises(setup.AssistantError):
                setup.update_profile(p, {"profile_id": "с пробелом"}, log=lambda *_: None)
            r = setup.update_profile(p, {"profile_id": "ivan"}, log=lambda *_: None)
            self.assertEqual((r["profile"], r["changed"]), ("ivan", ["имя профиля"]))
            moved = Profile("ivan", t.profiles)
            self.assertEqual(moved.vault_prefix, "профили/ivan")
            self.assertEqual(default_profile_name(t.profiles), "ivan")
            self.assertFalse((t.profiles / "example").exists())

    def test_answers_from_criteria(self):
        a = setup.answers_from_criteria(setup.build_criteria(ANSWERS))
        self.assertEqual((a["salary"], a["office"], a["hybrid"]), ("250000", True, True))
        self.assertEqual(a["important"], "производство\nкрупная компания")
        self.assertEqual(a["not_ok"], "постоянные командировки")
        b = setup.answers_from_criteria(setup.build_criteria({**ANSWERS, "part_time": False, "hybrid": False}))
        self.assertEqual((b["salary"], b["hybrid"]), ("250000", False))
        with TempProfile() as t:                       # пустая анкета — ответы берутся из критериев
            name = setup.create_profile(ANSWERS, t.profiles, log=lambda *_: None)
            p = Profile(name, t.profiles)
            (p.dir / setup.ANSWERS_FILE).write_text('{"salary": "", "important": "", "not_ok": ""}', encoding="utf-8")
            self.assertEqual(setup.answers_from_profile(p)["not_ok"], "постоянные командировки")

    def test_other_city(self):
        reply = {"items": [{"id": "4831", "text": "Верх-Тула", "parent": {"text": "Новосибирская область"}},
                           {"id": "92", "text": "Тула", "parent": {"text": "Тульская область"}}]}
        self.assertEqual(setup.find_area("тула", lambda url: reply),
                         {"id": "92", "name": "Тула", "region": "Тульская область"})      # точное совпадение
        self.assertIsNone(setup.find_area("Нетакого", lambda url: {"items": []}))
        self.assertEqual(setup.find_area("Москва")["id"], "1")                             # из списка — без сети
        answers = {**ANSWERS, "city": "Тула", "city_area": "92"}
        with TempProfile() as t:
            p = Profile(setup.create_profile(answers, t.profiles, log=lambda *_: None), t.profiles)
            self.assertEqual(p.search_where[0], ("Тула", "area=92"))
            self.assertIn("К1. Локация и формат: Тула (офис или гибрид)", read_text(p.criteria_file))
            a = setup.answers_from_profile(p)
            self.assertEqual((a["city"], a["city_area"]), ("Тула", "92"))

    def test_criteria_history(self):
        from vacancy_assistant import criteria_history as H
        with TempProfile() as t:
            p = t.profile
            first = p.read_criteria()
            H.record(p, first, "текущие критерии")
            setup.update_profile(p, {"criteria": first + "\n+ облака."}, log=lambda *_: None)
            H.record(p, first, "повтор", {"всего": 10, "совпало": 9, "пропущено": 0, "лишних": 1})
            H.record(p, first, "повтор", {"всего": 10, "совпало": 9, "пропущено": 0, "лишних": 1})   # без дублей
            vs = {v["current"]: v for v in H.versions(Profile("example", t.profiles))}
            self.assertEqual(len(vs), 2)                          # прежний текст и новая ручная версия
            self.assertEqual((vs[False]["measures"], vs[False]["measure"]["совпало"]), (1, 9))
            self.assertEqual((vs[True]["kind"], vs[True]["measure"]), ("manual", None))   # ручная, не проверялась
            with self.assertRaises(setup.AssistantError):
                H.delete(Profile("example", t.profiles), vs[True]["id"])          # текущую удалять нельзя
            with self.assertRaises(setup.AssistantError):
                H.delete(Profile("example", t.profiles), vs[False]["id"])         # с замером — нельзя
            setup.update_profile(Profile("example", t.profiles), {"criteria": first + "\n+ данные."}, log=lambda *_: None)
            p2 = Profile("example", t.profiles)
            manual_old = next(v for v in H.versions(p2) if v["kind"] == "manual" and not v["current"])
            H.delete(p2, manual_old["id"])                                          # ручная без прогонов — можно
            self.assertNotIn(manual_old["id"], [v["id"] for v in H.versions(p2)])
            letter = read_text(p2.letter_example)                                   # образец письма — так же
            setup.update_profile(p2, {"letter": letter + "\nP.S."}, log=lambda *_: None)
            lv = H.versions(Profile("example", t.profiles), "letter")
            self.assertEqual(sorted((v["current"], v["kind"]) for v in lv), [(False, "other"), (True, "manual")])

    def test_required_answers(self):
        with TempProfile() as t:
            for key in ("name", "titles", "resume"):
                with self.assertRaises(setup.AssistantError):
                    setup.create_profile({**ANSWERS, key: ""}, t.profiles, log=lambda *_: None)

if __name__ == "__main__":
    unittest.main()
