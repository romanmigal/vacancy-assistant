"""Актуальность вакансии по кнопке «Разобрать заново»: hh.ru — 404 или «в архиве», другие сайты — 404/410;
hh — только при включённом поиске; итог и дата проверки — в разборе, в таблице и карточке."""
import time
import unittest
from datetime import date

from helpers import VACANCY_HTML, TempProfile, fake_model

from vacancy_assistant import actual, analysis, app as A, hh, setup, sites
from vacancy_assistant.profile import Profile

DICT = '<template>{&#34;applicant.negotiations.vacancyArchived&#34;:&#34;Вакансия в архиве&#34;}</template>'   # словарь — на каждой
STATUS = '<template>{&#34;status&#34;:{&#34;archived&#34;:ARCH,&#34;disabled&#34;:false,&#34;hiddenInArchive&#34;:false}}</template>'
OPEN_PAGE = VACANCY_HTML.replace("<body>", "<body>" + DICT + STATUS.replace("ARCH", "false"))
ARCHIVED = VACANCY_HTML.replace("<body>", "<body>" + DICT + STATUS.replace("ARCH", "true"))
LUTIK = ("<html><head><title>Директор по ИТ</title></head><body><h1>Директор по ИТ</h1><p>ООО Лютик</p>"
         + "<p>Обязанности: руководить ИТ, строить команду, отвечать за бюджет и подрядчиков. </p>" * 8 + "</body></html>")


class Actual(unittest.TestCase):
    def setUp(self):
        self.t = TempProfile().__enter__()
        self.t.add_vacancy(1, "ИТ-директор")
        analysis.analyze(self.t.profile, log=lambda *_: None, ask=fake_model)
        self.path = next(self.t.profile.results.glob("01 *.md"))

    def tearDown(self):
        self.t.__exit__(None, None, None)

    def test_hh_pages(self):
        self.assertEqual(actual.hh_state(OPEN_PAGE), actual.OPEN)                      # «Вакансия в архиве» из словаря — не в счёт
        self.assertEqual(actual.hh_state(ARCHIVED), actual.GONE)
        self.assertEqual(actual.hh_state(OPEN_PAGE.replace("&#34;disabled&#34;:false", "&#34;disabled&#34;:true")), actual.GONE)
        self.assertEqual(actual.hh_state(""), actual.GONE)                             # 404 — hh.fetch отдаёт ""
        self.assertIsNone(actual.hh_state(VACANCY_HTML))                               # нет данных о статусе — не знаем

    def test_archived_on_download(self):
        """Вакансию скачали уже закрытой: плашка «В архиве с …» не попадает в название, разбор сразу «закрыта»."""
        page = ARCHIVED.replace("ИТ-директор</span></h1>", "ИТ-директор В архиве с 27 октября 2026</span></h1>", 1)
        self.assertIn("В архиве с 27", page)
        title, _, text = hh.vacancy_markdown(page, "100777")
        self.assertEqual(title, "ИТ-директор")
        self.assertIn("**На hh.ru:** вакансия в архиве", text)
        path = hh.add_vacancies(self.t.profile, ["100777"], log=lambda *_: None, fetch_page=lambda url: page)[0]
        analysis.analyze(self.t.profile, log=lambda *_: None, ask=fake_model, only=[path.name])
        self.assertEqual(actual.read(self.t.profile.results / path.name)["closed"], date.today().isoformat())
        title, _, text = hh.vacancy_markdown(OPEN_PAGE, "100778")                      # открытая — без пометки
        self.assertNotIn("в архиве", text)

    def test_record(self):
        self.assertEqual(actual.read(self.path), {"checked": "", "closed": ""})      # не проверялась
        actual.record(self.path, actual.OPEN, date(2026, 10, 20))
        self.assertEqual(actual.read(self.path), {"checked": "2026-10-20", "closed": ""})
        actual.record(self.path, actual.GONE, date(2026, 10, 25))
        actual.record(self.path, actual.GONE, date(2026, 10, 27))
        self.assertEqual(actual.read(self.path), {"checked": "2026-10-27", "closed": "2026-10-25"})   # закрыта с первой
        actual.record(self.path, None, date(2026, 10, 28))                             # не узнали — как было
        self.assertEqual(actual.read(self.path)["checked"], "2026-10-27")
        actual.record(self.path, actual.OPEN, date(2026, 10, 29))                      # снова открыта — пометку сняли
        self.assertEqual(actual.read(self.path), {"checked": "2026-10-29", "closed": ""})

    def test_hh_off_no_request(self):
        setup.set_hh_auto(self.t.profile, False, False)
        p, calls, lines = Profile("example", self.t.profiles), [], []
        state = actual.check_hh(p, "https://hh.ru/vacancy/100001", lambda url: calls.append(url) or VACANCY_HTML, lines.append)
        self.assertEqual((state, calls), (None, []))                                    # к hh не ходили
        self.assertIn("поиск на hh выключен", lines[0])

    def test_other_site(self):
        seen = {}
        path = sites.add_pages(self.t.profile, ["https://lutik.ru/v/7"], log=lambda *_: None,
                               fetch_page=lambda url: LUTIK, ask=fake_model)[0]
        sites.refresh(self.t.profile, path, log=lambda *_: None, fetch_page=lambda url: LUTIK, ask=fake_model, seen=seen)
        self.assertEqual(seen["actual"], actual.OPEN)
        gone = lambda url: (_ for _ in ()).throw(sites.Gone("Страницы больше нет (ответ 404)"))
        sites.refresh(self.t.profile, path, log=lambda *_: None, fetch_page=gone, seen=seen)
        self.assertEqual(seen["actual"], actual.GONE)
        broken = lambda url: (_ for _ in ()).throw(sites.AssistantError("нет связи"))
        sites.refresh(self.t.profile, path, log=lambda *_: None, fetch_page=broken, seen=seen)
        self.assertIsNone(seen["actual"])                                               # нет связи — не знаем


class ActualApp(unittest.TestCase):
    def setUp(self):
        self.t = TempProfile().__enter__()
        self.t.add_vacancy(1, "ИТ-директор")
        self.page = OPEN_PAGE
        self.app = A.App(self.t.profiles, fetch_page=lambda url: self.page, ask=fake_model,
                         check=lambda: {"ollama": True, "model_ok": True})
        self.app.handle("POST", "/api/run", {}, {"profile": "example", "action": "analyze"})
        self.wait()

    def tearDown(self):
        self.t.__exit__(None, None, None)

    def wait(self):
        for _ in range(1200):
            tasks = self.app.handle("GET", "/api/jobs", {"profile": ["example"]}, {})["tasks"]
            if tasks and not any(t["status"] in ("queued", "running") for t in tasks):
                self.assertEqual(tasks[-1]["error"], "")
                return
            time.sleep(0.05)
        self.fail("задача не закончилась")

    def row(self):
        return self.app.handle("GET", "/api/state", {"profile": ["example"]}, {})["rows"][0]

    def test_refresh_card(self):
        self.assertEqual(self.row()["actual"], {"checked": "", "closed": ""})
        self.app.handle("POST", "/api/run", {}, {"profile": "example", "action": "refresh_card", "n": 1})
        self.wait()
        today = date.today().isoformat()
        self.assertEqual(self.row()["actual"], {"checked": today, "closed": ""})       # открыта
        self.page = ARCHIVED
        self.app.handle("POST", "/api/run", {}, {"profile": "example", "action": "refresh_card", "n": 1})
        self.wait()
        self.assertEqual(self.row()["actual"], {"checked": today, "closed": today})    # в архиве — закрыта
        self.assertEqual(self.row()["stage"], "full")                                  # разбор всё равно сделан


if __name__ == "__main__":
    unittest.main()
