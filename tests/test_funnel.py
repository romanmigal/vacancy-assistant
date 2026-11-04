"""Воронка отклика: этапы с датами и историей, история статусов, разделы, предложение Архива, даты статусов контактов, сводка."""
import unittest
from datetime import date, datetime, timedelta

from helpers import TempProfile, fake_model

from vacancy_assistant import analysis, app as A, contacts, funnel, summary
from vacancy_assistant.errors import AssistantError
from vacancy_assistant.files import read_prop, set_prop
from vacancy_assistant.textio import read_text

D = date(2026, 10, 20)


class Funnel(unittest.TestCase):
    def setUp(self):
        self.t = TempProfile().__enter__()
        self.t.add_vacancy(1, "Директор по ИТ")
        self.t.add_vacancy(2, "CTO", company="ООО Второй")
        analysis.analyze(self.t.profile, log=lambda *_: None, ask=fake_model)
        self.path = next(self.t.profile.results.glob("01 *.md"))

    def tearDown(self):
        self.t.__exit__(None, None, None)

    def test_old_analysis_without_props(self):
        self.assertEqual(funnel.read(self.path), {"stage": "", "date": "", "history": [], "statuses": []})
        self.assertNotIn("этап", read_text(self.path))
        self.assertEqual(funnel.read(self.t.tmp / "нет.md")["history"], [])

    def test_stages_and_history(self):
        f, section, archive = funnel.set_stage(self.path, "applied", D, "new")
        self.assertEqual((section, archive), ("yes", False))                     # отклик — в «Интересно»
        f, section, _ = funnel.set_stage(self.path, "applied", D + timedelta(days=1), "yes")
        self.assertEqual((len(f["history"]), f["date"], section), (1, "2026-10-21", ""))   # тот же этап — новая дата
        funnel.set_stage(self.path, "answered", date(2026, 10, 23), "yes")
        f, section, _ = funnel.set_stage(self.path, "hr", date(2026, 10, 28), "yes")
        self.assertEqual(section, "interview")
        self.assertEqual(read_prop(self.path, "этапы"), "Откликнулся 21.10.2026; Ответили 23.10.2026; Интервью с HR 28.10.2026")
        self.assertEqual(read_prop(self.path, "этап"), "Интервью с HR")
        self.assertEqual(funnel.read(self.path), f)                               # прочитали то же, что записали
        f, section, archive = funnel.set_stage(self.path, "rejected", date(2026, 11, 2), "interview")
        self.assertEqual((section, archive), ("", True))                          # Архив — только предложить
        self.assertFalse(funnel.set_stage(self.path, "silent", D, "no")[2])       # уже в Архиве
        with self.assertRaises(AssistantError):
            funnel.set_stage(self.path, "bogus")

    def test_reanalysis_keeps_stages(self):
        funnel.set_stage(self.path, "applied", D, "new")
        analysis.analyze(self.t.profile, log=lambda *_: None, ask=fake_model, only=[self.path.name])   # разбор заново
        self.assertEqual(funnel.read(self.path)["stage"], "applied")
        self.assertEqual(funnel.set_stage(self.path, "")[0]["stage"], "")                             # этап сняли
        self.assertEqual(len(funnel.read(self.path)["history"]), 1)                                    # история осталась

    def test_edits_merge_while_typing(self):
        at = lambda day, h, m: datetime(2026, 10, day, h, m, 0)
        rec = lambda field, text, before, when: funnel.record_edit(self.t.profile, self.path, field, text, before, when)
        rec("comment", "Звонила", "", at(20, 10, 0))
        rec("comment", "Звонила Анна", "Звонила", at(20, 10, 1))                 # дописывает — та же правка
        rec("referrer", "Иван Петров, CIO", "", at(20, 10, 3))
        rec("comment", "Звонила Анна, ждём финал", "Звонила Анна", at(20, 10, 9))   # пауза меньше 10 минут
        rec("comment", "Финал 30.10", "Звонила Анна, ждём финал", at(20, 11, 0))    # через час — новая правка
        rec("comment", "Звонила Анна, ждём финал", "Финал 30.10", at(20, 11, 2))    # вернул как было — правки нет
        rec("referrer", "", "Иван Петров, CIO", at(23, 9, 0))                      # очистили — тоже правка
        self.assertEqual([(e["date"][-2:], e["time"], e["field"], e["text"]) for e in funnel.read_edits(self.t.profile, self.path)],
                         [("20", "10:00:00", "comment", "Звонила Анна, ждём финал"),   # время — начала правки
                          ("20", "10:03:00", "referrer", "Иван Петров, CIO"), ("23", "09:00:00", "referrer", "")])
        rec("comment", "x", "", D)                                                 # дата без времени — тоже можно
        other = next(self.t.profile.results.glob("02 *.md"))
        funnel.record_edit(self.t.profile, other, "comment", "старый", "старый")   # ничего не поменялось
        self.assertEqual(funnel.read_edits(self.t.profile, other), [])
        funnel.record_edit(self.t.profile, other, "comment", "", "был до истории")  # очистили давний комментарий
        self.assertEqual(funnel.read_edits(self.t.profile, other)[0]["text"], "")
        with self.assertRaises(AssistantError):
            rec("title", "x", "", D)

    def test_times_and_old_records(self):
        funnel.set_stage(self.path, "applied", datetime(2026, 10, 20, 10, 15, 2), "new")
        funnel.record_status(self.path, "yes", datetime(2026, 10, 20, 10, 15, 2))
        self.assertEqual(read_prop(self.path, "этапы"), "Откликнулся 20.10.2026 10:15:02")
        self.assertEqual(read_prop(self.path, "статусы"), "Интересно 20.10.2026 10:15:02")
        set_prop(self.path, "этапы", "Ответили 18.10.2026; Откликнулся 20.10.2026 10:15:02")   # старая запись — без времени
        f = funnel.read(self.path)
        self.assertEqual([(h["stage"], h["date"], h["time"]) for h in f["history"]],
                         [("answered", "2026-10-18", ""), ("applied", "2026-10-20", "10:15:02")])
        self.assertEqual(f["statuses"], [{"status": "yes", "date": "2026-10-20", "time": "10:15:02"}])

    def test_contact_status_date(self):
        cid = contacts.upsert(self.t.profile, {"name": "Иван Петров", "company": "ООО Пример", "status": "wrote"})
        items = contacts.load(self.t.profile)
        self.assertEqual(items[0]["status_date"], date.today().isoformat())
        self.assertEqual(contacts.public(items)[0]["status_date"], date.today().isoformat())
        contacts.upsert(self.t.profile, {**items[0], "status": ""})
        self.assertEqual(contacts.load(self.t.profile)[0]["status_date"], "")
        self.assertTrue(cid)

    def test_updated(self):
        self.assertEqual(funnel.updated(funnel.read(self.path), []), "")                    # ничего не меняли
        funnel.set_stage(self.path, "applied", D, "new")
        self.assertEqual(funnel.updated(funnel.read(self.path), []), "2026-10-20")          # только этап
        comment = {"date": "2026-10-22", "time": "", "field": "comment", "text": "Звонили", "last": "2026-10-23T09:00:00"}
        referrer = {"date": "2026-10-25", "time": "", "field": "referrer", "text": "Иван", "last": ""}
        self.assertEqual(funnel.updated(None, [comment]), "2026-10-23")                     # только комментарий — последнее сохранение
        self.assertEqual(funnel.updated(funnel.read(self.path), [comment, referrer]), "2026-10-23")   # позднее; референсер не в счёт
        funnel.set_stage(self.path, "hr", date(2026, 10, 28), "yes")
        self.assertEqual(funnel.updated(funnel.read(self.path), [comment]), "2026-10-28")
        funnel.record_status(self.path, "no")                                                # статус не в счёт
        self.assertEqual(funnel.updated(funnel.read(self.path), [comment]), "2026-10-28")

    def test_summary_columns(self):
        funnel.set_stage(self.path, "hr", date(2020, 1, 10), "yes")
        summary.write_summary(self.t.profile, log=lambda *_: None)
        text = read_text(self.t.profile.summary)
        self.assertIn("| Зарплата | Этап |", text)
        self.assertIn("| Интервью с HR 10.01 |", text)
        self.assertNotIn("Шаг", text)


class FunnelApi(unittest.TestCase):
    def setUp(self):
        self.t = TempProfile().__enter__()
        self.t.add_vacancy(1, "Директор по ИТ")
        self.t.add_vacancy(2, "Без разбора")
        analysis.analyze(self.t.profile, log=lambda *_: None, ask=fake_model)
        next(self.t.profile.results.glob("02 *.md")).unlink()
        self.app = A.App(self.t.profiles)

    def tearDown(self):
        self.t.__exit__(None, None, None)

    def call(self, path, body=None):
        try:
            return 200, self.app.handle("POST" if body is not None else "GET", path, {}, body or {})
        except AssistantError as e:
            return 400, {"error": str(e)}

    def test_routes(self):
        status, r = self.call("/api/funnel/stage", {"profile": "example", "n": 1, "stage": "applied", "date": "2026-10-20"})
        self.assertEqual((status, r["status"], r["archive"], r["funnel"]["date"]), (200, "yes", False, "2026-10-20"))
        self.assertEqual(summary.read_statuses(self.t.profile)["s1"], "yes")
        r = self.call("/api/funnel/stage", {"profile": "example", "n": 1, "stage": "manager", "date": "28.10.2026"})[1]
        self.assertEqual(r["status"], "interview")
        r = self.call("/api/funnel/stage", {"profile": "example", "n": 1, "stage": "rejected"})[1]
        self.assertEqual((r["status"], r["archive"]), ("interview", True))
        self.assertEqual(summary.read_statuses(self.t.profile)["s1"], "interview")   # в Архив — только по кнопке
        st = self.app.handle("GET", "/api/state", {"profile": ["example"]}, {})
        self.assertEqual(st["rows"][0]["funnel"]["stage"], "rejected")
        self.assertEqual([h["stage"] for h in st["rows"][0]["funnel"]["history"]], ["applied", "manager", "rejected"])
        self.assertNotIn("today", st)
        self.assertEqual(list(st["stages"][0]), ["applied", "Откликнулся"])
        self.assertEqual([x["status"] for x in st["rows"][0]["funnel"]["statuses"]], ["yes", "interview"])   # сами
        self.call("/api/status", {"profile": "example", "n": 1, "value": "no"})
        self.call("/api/status", {"profile": "example", "n": 1, "value": "no"})                # тот же — не пишем
        self.call("/api/status", {"profile": "example", "n": 2, "value": "yes"})               # без разбора — не падает
        result = next(self.t.profile.results.glob("01 *.md"))
        statuses = [x["status"] for x in funnel.read(result)["statuses"]]
        self.assertEqual(statuses, ["yes", "interview", "no"])
        self.assertRegex(read_prop(result, "статусы"), r"^Интересно \d\d\.\d\d\.\d{4} \d\d:\d\d:\d\d; ")
        self.call("/api/note", {"profile": "example", "n": 1, "text": "Звонила Анна"})
        self.call("/api/note", {"profile": "example", "n": 1, "text": "Звонила Анна"})               # то же — не пишем
        self.call("/api/referrer", {"profile": "example", "n": 1, "text": "Иван Петров, CIO"})
        edits = self.app.handle("GET", "/api/vacancy", {"profile": ["example"], "n": ["1"]}, {})["edits"]
        self.assertEqual([(e["field"], e["text"]) for e in edits], [("comment", "Звонила Анна"), ("referrer", "Иван Петров, CIO")])
        self.assertEqual(self.call("/api/funnel/stage", {"profile": "example", "n": 2, "stage": "applied"})[0], 400)

    def test_updated_and_saved(self):
        today = date.today().isoformat()
        rows = lambda: {r["n"]: r for r in self.app.handle("GET", "/api/state", {"profile": ["example"]}, {})["rows"]}
        self.assertEqual((rows()[1]["updated"], rows()[2]["updated"]), ("", ""))
        r = self.call("/api/note", {"profile": "example", "n": 1, "text": "Звонила Анна"})[1]
        self.assertEqual(r["updated"], today)                                          # окно сразу ставит дату
        self.assertEqual(rows()[1]["updated"], today)
        self.call("/api/funnel/stage", {"profile": "example", "n": 1, "stage": "applied", "date": "2026-10-20"})
        self.assertEqual(rows()[1]["updated"], today)                                  # комментарий позднее этапа
        vacancy = self.app.handle("GET", "/api/vacancy", {"profile": ["example"], "n": ["1"]}, {})["vacancy"]
        self.assertNotIn("Сохранено", vacancy)                                         # дата — в панели полей
        self.assertIn("**Ссылка:**", vacancy)
        self.assertIn("**Сохранено:**", read_text(next(self.t.profile.vacancies.glob("01 *.md"))))   # файл как был


if __name__ == "__main__":
    unittest.main()
