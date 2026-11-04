"""Окно программы: сервер на 127.0.0.1 и его API — на копии профиля-примера, без сети и без Ollama."""
import base64
import json
import threading
import time
import unittest
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

from helpers import VACANCY_HTML, TempProfile, fake_model

from vacancy_assistant import app as A, ratings, summary as S
from vacancy_assistant.files import numbered_files, read_note
from vacancy_assistant.textio import read_text, write_text


class AppServer(unittest.TestCase):
    def setUp(self):
        self.t = TempProfile().__enter__()
        self.app = A.App(self.t.profiles, fetch_page=lambda url: VACANCY_HTML, ask=fake_model,
                         check=lambda: {"ollama": True, "model_ok": True})
        self.server = A.make_server(self.app, port=0)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.t.__exit__(None, None, None)

    def call(self, path, body=None, token=None, host=None):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"X-Token": token or self.app.token, "Content-Type": "application/json"})
        if host:
            req.add_header("Host", host)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def test_all_scripts_at_once(self):
        """Окно просит все скрипты разом — ни один не должен сброситься (очередь соединений была 5)."""
        from concurrent.futures import ThreadPoolExecutor
        import re
        with urllib.request.urlopen(self.base + "/") as r:
            page = r.read().decode("utf-8")
        files = re.findall(r'(?:src|href)="((?:js|style)[^"]*)"', page) * 2
        self.assertGreater(len(files), 20)

        def get(f):
            with urllib.request.urlopen(f"{self.base}/{f}") as r:
                return r.status
        with ThreadPoolExecutor(len(files)) as pool:
            self.assertEqual(set(pool.map(get, files)), {200})

    def tasks(self, profile="example"):
        return self.call(f"/api/jobs?profile={profile}")[1]["tasks"]

    def wait_job(self):
        """Ждёт, пока у профиля не останется задач в очереди и в работе; возвращает последнюю."""
        for _ in range(1200):                         # до минуты: на машинах CI с Windows запись на диск медленная
            tasks = self.tasks()
            if tasks and not any(t["status"] in ("queued", "running") for t in tasks):
                return {**tasks[-1], "stopped": tasks[-1]["status"] == "stopped"}
            time.sleep(0.05)
        self.fail("задача не закончилась")

    def test_page_has_token(self):
        with urllib.request.urlopen(self.base + "/") as r:
            self.assertIn(self.app.token, r.read().decode("utf-8"))

    def test_help_pages(self):
        import http.client
        from urllib.parse import quote
        port = self.server.server_address[1]

        def get(path):
            c = http.client.HTTPConnection("127.0.0.1", port)
            c.request("GET", path)
            r = c.getresponse()
            out = (r.status, r.getheader("Content-Type"), r.read())
            c.close()
            return out
        self.assertEqual(get("/help")[0], 301)                                       # → /help/
        code, ctype, body = get("/help/")
        self.assertEqual((code, ctype.split(";")[0]), (200, "text/html"))
        self.assertIn("<h1>Помощник по вакансиям</h1>", body.decode("utf-8"))           # README — страницей
        self.assertIn('src="docs/', body.decode("utf-8"))
        self.assertEqual(get("/help/docs/" + quote("окно.png"))[1], "image/png")        # картинки к нему
        self.assertEqual(get("/help/docs/" + quote("Настройка критериев.md"))[0], 200)
        code, _, body = get("/help/docs/" + quote("Оценка не совпадает с вашей.md"))       # гид из карточки
        self.assertEqual(code, 200)
        self.assertIn("<h1>Оценка программы не совпадает с вашей: что делать</h1>", body.decode("utf-8"))
        for bad in ("/help/../vacancy_assistant/app.py", "/help/docs/..%2Fsettings.py", "/help/docs/none.md"):
            self.assertEqual(get(bad)[0], 404, bad)

    def test_static_files(self):
        import http.client
        with urllib.request.urlopen(self.base + "/") as r:
            page = r.read().decode("utf-8")
        for path in ["style.css", "icon.svg"] + [f"js/{n}" for n in ("core.js", "main.js", "wizard.js", "calibration.js", "settings.js")]:
            self.assertIn(path, page)
            with urllib.request.urlopen(f"{self.base}/{path}") as r:            # все файлы окна отдаются
                self.assertTrue(r.headers["Content-Type"].startswith(("text/", "image/svg")))
                self.assertGreater(len(r.read()), 100)
        port = self.server.server_address[1]
        for path in ("/js/..%2Fapp.py", "/../app.py", "/js/missing.js", "/settings.py"):
            c = http.client.HTTPConnection("127.0.0.1", port)
            c.request("GET", path)
            self.assertEqual(c.getresponse().status, 404, path)                  # только файлы окна
            c.close()

    def test_home_network_access(self):
        import http.client
        self.app.lan_port = 0
        self.addCleanup(self.app.stop_lan)
        self.assertEqual(self.call("/api/network", {"enabled": True})[0], 400)            # без пароля не включить
        self.assertEqual(self.call("/api/network", {"enabled": True, "password": "123"})[0], 400)   # короткий
        code, net = self.call("/api/network", {"enabled": True, "password": "secret-1"})
        self.assertEqual((code, net["enabled"], net["running"]), (200, True, True))
        self.assertNotIn("secret-1", read_text(self.t.profiles / "доступ из сети.json"))  # только хэш
        port = self.app.lan.server_address[1]

        def lan(method, path, body=None, headers=None):
            c = http.client.HTTPConnection("127.0.0.1", port)
            c.request(method, path, body, headers or {})
            r = c.getresponse()
            out = (r.status, r.getheader("Set-Cookie"), r.read().decode("utf-8"))
            c.close()
            return out

        status, _, page = lan("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn('name="password"', page)                                   # сначала — вход
        self.assertNotIn(self.app.token, page)
        self.assertEqual(lan("GET", "/api/state", headers={"X-Token": self.app.token})[0], 401)
        form = {"Content-Type": "application/x-www-form-urlencoded"}
        self.assertEqual(lan("POST", "/login", "password=wrong", form)[0], 401)
        status, cookie, _ = lan("POST", "/login", "password=secret-1", form)
        self.assertEqual(status, 303)
        session = {"Cookie": cookie.split(";")[0], "X-Token": self.app.token}
        status, _, page = lan("GET", "/", headers=session)
        self.assertIn("const REMOTE = true", page)
        self.assertEqual(lan("GET", "/api/state", headers=session)[0], 200)
        self.assertEqual(lan("POST", "/api/quit", "{}", session)[0], 403)        # выключить — только на основном
        self.assertEqual(lan("POST", "/api/network", '{"enabled": false}', session)[0], 403)
        for _ in range(5):
            lan("POST", "/login", "password=wrong", form)
        status, _, page = lan("POST", "/login", "password=secret-1", form)        # подбор — пауза даже для верного
        self.assertIn("Слишком много попыток", page)

        code, net = self.call("/api/network", {"enabled": False})
        self.assertEqual((net["enabled"], net["running"]), (False, False))

    def test_lan_ips_skip_vpn(self):
        from unittest import mock
        from vacancy_assistant import network
        ifconfig = ("lo0: flags=8049<UP,LOOPBACK,RUNNING> mtu 16384\n\tinet 127.0.0.1 netmask 0xff000000\n"
                    "en0: flags=8863<UP,BROADCAST,RUNNING> mtu 1500\n\tinet 192.168.1.20 netmask 0xffffff00\n"
                    "utun4: flags=8051<UP,POINTOPOINT,RUNNING> mtu 1500\n\tinet 172.18.0.1 --> 172.18.0.1\n")
        with mock.patch.object(network.sys, "platform", "darwin"), \
                mock.patch.object(network, "_run", lambda *cmd: ifconfig if cmd == ("ifconfig",) else ""):
            self.assertEqual(network.lan_ips(), ["192.168.1.20"])               # VPN и loopback — мимо
        with mock.patch.object(network.sys, "platform", "win32"), \
                mock.patch.object(network, "_run", lambda *cmd: "   IPv4-адрес. . . . : 192.168.1.7\n"):
            self.assertEqual(network.lan_ips(), ["192.168.1.7"])

    def test_criteria_changed_and_rescore(self):
        self.t.add_vacancy(1, "ИТ-директор")
        self.call("/api/run", {"profile": "example", "action": "analyze"})
        self.wait_job()
        card = lambda: self.call("/api/vacancy?profile=example&n=1")[1]
        self.assertFalse(card()["criteria_changed"])
        p = self.t.profile
        write_text(p.criteria_file, p.read_criteria() + "\n")                       # сохранили без правок
        self.assertFalse(card()["criteria_changed"])                                   # отпечаток тот же
        write_text(p.criteria_file, p.read_criteria() + "\n+ облака.\n")
        self.assertTrue(card()["criteria_changed"])
        self.call("/api/run", {"profile": "example", "action": "refresh_card", "n": 1})    # «Разобрать заново» в карточке
        self.assertEqual(self.wait_job()["error"], "")
        self.assertFalse(card()["criteria_changed"])                                   # переоценена по новым
        row = self.call("/api/state?profile=example")[1]["rows"][0]
        self.assertEqual(row["stage"], "full")                                         # «Разобрать заново» — всегда полный разбор

    def test_contact_in_state(self):
        """Почта для связи — одна константа, окно берёт её из состояния для «О программе»."""
        from vacancy_assistant import settings
        self.assertEqual(self.call("/api/state?profile=example")[1]["contact"], settings.CONTACT_EMAIL)
        self.assertIn(settings.CONTACT_EMAIL, (Path(__file__).parent.parent / "README.md").read_text(encoding="utf-8"))

    def test_rescore_all_changed(self):
        for n in (1, 2, 3):
            self.t.add_vacancy(n, "ИТ-директор" if n != 2 else "Начальник отдела ИТ")
        self.call("/api/run", {"profile": "example", "action": "analyze"})
        self.wait_job()
        self.call("/api/status", {"profile": "example", "n": 3, "value": "no"})
        rows = lambda: {r["n"]: r for r in self.call("/api/state?profile=example")[1]["rows"]}
        self.assertFalse(any(r["criteria_changed"] for r in rows().values()))
        p = self.t.profile
        write_text(p.criteria_file, p.read_criteria() + "\n+ облака.\n")
        self.assertTrue(all(r["criteria_changed"] for r in rows().values()))
        code, err = self.call("/api/run", {"profile": "example", "action": "rescore_all", "statuses": ["yes"]})
        self.assertEqual(code, 400)                                                    # в «интересно» таких нет
        self.call("/api/run", {"profile": "example", "action": "rescore_all", "statuses": ["new"]})
        job = self.wait_job()
        self.assertEqual(sum("Разбираю:" in line for line in job["log"]), 2)          # только «не обработано»
        r = rows()
        self.assertEqual({n: r[n]["criteria_changed"] for n in r}, {1: False, 2: False, 3: True})
        self.assertEqual(r[2]["stage"], "full")                                        # полным разбором

    def test_rescore_all_mode_all(self):
        """«Все вакансии в выбранных разделах»: пересчёт и без смены данных, только разобранные."""
        for n in (1, 2, 3):
            self.t.add_vacancy(n, "ИТ-директор")
        self.call("/api/run", {"profile": "example", "action": "analyze"})
        self.wait_job()
        self.call("/api/status", {"profile": "example", "n": 3, "value": "no"})
        self.t.add_vacancy(4, "CTO")                                                   # не разобрана
        code, err = self.call("/api/run", {"profile": "example", "action": "rescore_all", "statuses": ["new"]})
        self.assertEqual(code, 400)                                                    # устаревших нет
        self.assertIn("Все вакансии", err["error"])
        self.call("/api/run", {"profile": "example", "action": "rescore_all", "statuses": ["new"], "mode": "all"})
        job = self.wait_job()
        self.assertEqual(sum("Разбираю:" in line for line in job["log"]), 2)          # 1 и 2: без архива и без 4
        self.assertEqual(sorted(A.analyzed_with_status(self.t.profile, {"new", "no"})),
                         [f.name for n, f in sorted(numbered_files(self.t.profile.vacancies).items()) if n != 4])

    def test_calibration_shows_flag_and_note(self):
        self.t.add_vacancy(1, "ИТ-директор")
        self.call("/api/run", {"profile": "example", "action": "analyze"})
        self.wait_job()
        self.call("/api/flag", {"profile": "example", "n": 1, "on": True})
        self.call("/api/note", {"profile": "example", "n": 1, "text": "нет разработки"})
        v = self.call("/api/calibration?profile=example")[1]["unrated"][0]
        self.assertEqual((v["flag"], v["note"]), (True, "нет разработки"))         # заметка — подсказка для «Почему»

    def test_one_stage_analysis(self):
        self.t.add_vacancy(1, "ИТ-директор")
        self.t.add_vacancy(2, "Начальник отдела ИТ")
        self.assertTrue(self.call("/api/state?profile=example")[1]["two_stage"])          # по умолчанию — две ступени
        self.call("/api/profile/settings", {"profile": "example", "two_stage": False})
        self.assertFalse(self.call("/api/state?profile=example")[1]["two_stage"])
        self.call("/api/run", {"profile": "example", "action": "analyze"})
        job = self.wait_job()
        self.assertFalse(any("короткая оценка" in line for line in job["log"]))
        rows = self.call("/api/state?profile=example")[1]["rows"]
        self.assertEqual({r["stage"] for r in rows}, {"full"})                              # и «нет» — полным разбором

    def test_switch_to_one_stage_reanalyzes_short_only(self):
        self.t.add_vacancy(1, "ИТ-директор")
        self.t.add_vacancy(2, "Начальник отдела ИТ")
        self.call("/api/run", {"profile": "example", "action": "analyze"})                # две ступени: 2 — только быстрая
        self.wait_job()
        stages = {r["n"]: r["stage"] for r in self.call("/api/state?profile=example")[1]["rows"]}
        self.assertEqual(stages, {1: "full", 2: "short"})
        self.call("/api/profile/settings", {"profile": "example", "two_stage": False})
        self.call("/api/run", {"profile": "example", "action": "refresh", "reanalyze": ["new"], "only_short": True})
        job = self.wait_job()
        self.assertEqual(sum("Оцениваю:" in line for line in job["log"]), 1)          # полный разбор есть — не трогаем
        stages = {r["n"]: r["stage"] for r in self.call("/api/state?profile=example")[1]["rows"]}
        self.assertEqual(stages, {1: "full", 2: "full"})

    def test_cloud_model_always_full_analysis(self):
        import json
        self.t.add_vacancy(1, "Начальник отдела ИТ")                                   # быстрая оценка сказала бы «нет»
        (self.t.profiles / "облако.json").write_text(json.dumps({"enabled": True, "auth_key": "k", "consent": True}),
                                                     encoding="utf-8")
        st = self.call("/api/state?profile=example")[1]
        self.assertEqual((st["cloud"], st["two_stage_setting"], st["two_stage"]), (True, True, False))
        self.call("/api/run", {"profile": "example", "action": "analyze"})
        self.assertEqual(self.wait_job()["error"], "")
        self.assertEqual(self.call("/api/state?profile=example")[1]["rows"][0]["stage"], "full")

    def test_first_run_without_profiles(self):
        import shutil
        shutil.rmtree(self.t.profiles / "example")
        code, state = self.call("/api/state")
        self.assertEqual((code, state["profiles"], state["profile"], state["rows"]), (200, [], None, []))
        ex = self.call("/api/setup/examples")[1]                              # образцы для мастера есть и без профилей
        self.assertIn("К1", ex["criteria"])
        self.assertTrue(ex["resume"].strip())

    def test_protection(self):
        self.assertEqual(self.call("/api/state", token="wrong-token")[0], 403)             # без ключа — нельзя
        self.assertEqual(self.call("/api/state", host="evil.example:80")[0], 403)    # чужой адрес — нельзя
        code, data = self.call("/api/state?profile=../example")                        # только папки профилей
        self.assertEqual(code, 400)

    def test_add_status_note_export(self):
        p = self.t.profile
        code, state = self.call("/api/state")
        self.assertEqual((code, state["profile"], state["rows"]), (200, "example", []))

        code, job = self.call("/api/run", {"profile": "example", "action": "add",
                                           "links": "https://hh.ru/vacancy/123456?from=x"})
        self.assertEqual(code, 200)
        job = self.wait_job()
        self.assertEqual(job["error"], "")
        self.assertTrue(any("оценка 8/10" in line for line in job["log"]))          # скачала и разобрала
        self.assertFalse(any("письм" in line.lower() for line in job["log"] if line.startswith("▶")))   # письма сами не пишутся

        row = self.call("/api/state?profile=example")[1]["rows"][0]
        self.assertEqual((row["n"], row["score"], row["status"], row["analyzed"]), (1, 8, "new", True))
        self.assertEqual(row["source"], "HH")                                         # откуда вакансия
        details = self.call("/api/vacancy?profile=example&n=1")[1]
        self.assertTrue(details["analysis"].startswith("Критерии:"))                 # без заголовка и паспорта
        self.assertIn("руководить ИТ", details["vacancy"])

        self.assertEqual(self.call("/api/status", {"profile": "example", "n": 1, "value": "yes"})[0], 200)
        self.assertEqual(S.read_statuses(p)["s1"], "yes")
        self.assertEqual(self.call("/api/status", {"profile": "example", "n": 1, "value": "maybe"})[0], 400)
        self.assertEqual(self.call("/api/status", {"profile": "example", "n": 1, "value": "interview"})[0], 200)
        self.assertEqual([v for v, _ in self.call("/api/state?profile=example")[1]["statuses"]],
                         ["new", "yes", "interview", "no"])                          # порядок разделов везде один
        self.call("/api/status", {"profile": "example", "n": 1, "value": "yes"})

        self.assertFalse(self.call("/api/state?profile=example")[1]["rows"][0]["flag"])
        self.call("/api/flag", {"profile": "example", "n": 1, "on": True})
        self.assertTrue(self.call("/api/state?profile=example")[1]["rows"][0]["flag"])
        self.assertEqual(S.read_statuses(p)["s1"], "yes")                           # статус не задет
        self.call("/api/flag", {"profile": "example", "n": 1, "on": False})
        self.assertEqual(S.read_flags(p), set())

        self.call("/api/note", {"profile": "example", "n": 1, "text": 'откликнулся,\n"ждём"'})
        result = next(p.results.glob("01 *.md"))
        self.assertEqual(read_note(result), 'откликнулся, "ждём"')
        self.assertEqual(self.call("/api/state?profile=example")[1]["rows"][0]["note"], 'откликнулся, "ждём"')
        example = self.call("/api/letter/example?profile=example")[1]["text"]             # письмо по своему образцу
        self.assertTrue(example)
        self.call("/api/run", {"profile": "example", "action": "letter", "n": 1, "example": "Короткий образец."})
        self.wait_job()
        self.assertEqual(read_text(p.letter_example).strip(), example)                    # образец профиля не тронут
        self.call("/api/run", {"profile": "example", "action": "letter", "n": 1, "example": "Новый образец.",
                               "save_example": True})
        self.wait_job()
        self.assertEqual(read_text(p.letter_example).strip(), "Новый образец.")
        self.assertEqual(len(self.call("/api/vacancy?profile=example&n=1")[1]["letters"]), 2)   # версии сохранились
        self.call("/api/run", {"profile": "example", "action": "refresh_card", "n": 1})    # карточка заново
        self.wait_job()
        self.assertEqual(self.call("/api/state?profile=example")[1]["rows"][0]["note"], 'откликнулся, "ждём"')
        self.call("/api/status", {"profile": "example", "n": 1, "value": "interview"})       # к интервью — истории STAR
        self.call("/api/run", {"profile": "example", "action": "interview", "n": 1})
        self.wait_job()
        d = self.call("/api/vacancy?profile=example&n=1")[1]
        self.assertIn("## 1. Запуск ИТ с нуля", d["interview"])
        self.assertIn("## Мои вопросы работодателю\n1. Кому подчиняется роль?", d["interview"])   # вопросы — тем же вызовом
        self.assertNotIn("<!--", d["interview"])
        self.assertTrue(d["interview_when"])
        self.call("/api/run", {"profile": "example", "action": "interview_questions", "n": 1})   # только вопросы заново
        self.wait_job()
        d = self.call("/api/vacancy?profile=example&n=1")[1]
        self.assertIn("## 1. Запуск ИТ с нуля", d["interview"])                    # истории остались
        self.assertIn("1. Какой бюджет ИТ на год?", d["interview"])
        self.assertNotIn("Кому подчиняется роль?", d["interview"])                  # прежние вопросы заменены
        self.assertEqual(d["interview"].count("## Мои вопросы работодателю"), 1)
        self.call("/api/status", {"profile": "example", "n": 1, "value": "yes"})
        csv = "First Name,Last Name,URL,Email Address,Company,Position,Connected On\nИван,Петров,,,Пример,CFO,\n"   # контакты
        self.call("/api/contacts/import", {"profile": "example", "name": "Connections.csv",
                                           "data": base64.b64encode(csv.encode()).decode()})
        self.assertEqual(self.call("/api/state?profile=example")[1]["rows"][0]["contacts"], 1)
        self.assertEqual([c["name"] for c in self.call("/api/vacancy?profile=example&n=1")[1]["referrer_candidates"]],
                         ["Иван Петров"])
        self.assertEqual(self.call("/api/contacts?profile=example")[1]["contacts"][0]["vacancies"], [{"n": 1, "exact": True}])
        ivan = self.call("/api/contacts?profile=example")[1]["contacts"][0]                 # выбран из контактов
        self.call("/api/referrer", {"profile": "example", "n": 1, "text": "Иван Петров, CFO, Пример", "contact_id": ivan["id"]})
        row = self.call("/api/state?profile=example")[1]["rows"][0]
        self.assertEqual(row["referrer_contact"]["short"], "Иван Петров, CFO")
        self.call("/api/contacts/save", {"profile": "example", "contact": {**ivan, "name": "Иван Сергеевич Петров"}})
        row = self.call("/api/state?profile=example")[1]["rows"][0]                        # поправили — и в вакансии
        self.assertEqual((row["referrer"], row["referrer_contact"]["short"]),
                         ("Иван Сергеевич Петров, CFO, Пример", "Иван Сергеевич Петров, CFO"))
        self.call("/api/referrer", {"profile": "example", "n": 1, "text": "Иван Петров, CFO"})
        row = self.call("/api/state?profile=example")[1]["rows"][0]
        self.assertEqual((row["referrer"], row["note"]), ("Иван Петров, CFO", 'откликнулся, "ждём"'))
        self.call("/api/run", {"profile": "example", "action": "refresh_card", "n": 1})              # новый разбор — поля на месте
        self.wait_job()
        self.assertEqual(self.call("/api/state?profile=example")[1]["rows"][0]["referrer"], "Иван Петров, CFO")

        self.assertIn("## Интересно (1)", read_text(p.summary))       # сводка выгружена сама вместе с панелью

    def test_violations_in_rows(self):
        self.t.add_vacancy(1, "Начальник отдела ИТ")
        self.call("/api/run", {"profile": "example", "action": "analyze"})
        self.wait_job()
        result = next(self.t.profile.results.glob("01 *.md"))
        result.write_text(result.read_text(encoding="utf-8").replace("К1: ✅", "К1: ❌"), encoding="utf-8")
        row = self.call("/api/state")[1]["rows"][0]
        self.assertEqual([(v["n"], v["name"]) for v in row["violations"]], [("1", "Локация")])
        self.assertEqual(self.tasks()[-1]["count"] > 0, True)

    def test_refresh_makes_full_analysis(self):
        self.t.add_vacancy(1, "Начальник отдела ИТ")                                # «нет» — только короткая оценка
        self.call("/api/run", {"profile": "example", "action": "analyze"})
        self.wait_job()
        self.assertEqual(self.call("/api/state")[1]["rows"][0]["stage"], "short")
        self.call("/api/run", {"profile": "example", "action": "refresh_card", "n": 1})
        self.assertEqual(self.wait_job()["error"], "")
        self.assertEqual(self.call("/api/state")[1]["rows"][0]["stage"], "full")

    def test_letter_button_ignores_score(self):
        self.t.add_vacancy(1, "Начальник отдела ИТ")                                # модель даст 3 и «нет»
        self.call("/api/run", {"profile": "example", "action": "analyze"})
        self.wait_job()
        self.assertFalse(self.call("/api/state?profile=example")[1]["rows"][0]["letter"])   # ниже порога — без письма
        self.call("/api/run", {"profile": "example", "action": "letter", "n": 1})
        self.assertEqual(self.wait_job()["error"], "")
        self.assertTrue(self.call("/api/state?profile=example")[1]["rows"][0]["letter"])    # по кнопке — пишется

    def test_stop(self):
        for n in range(1, 4):
            self.t.add_vacancy(n, f"ИТ-директор {n}")
        started = threading.Event()

        def slow_model(prompt, *args):
            started.set()
            time.sleep(0.3)
            return fake_model(prompt, *args)
        self.app.ask = slow_model
        tid = self.call("/api/run", {"profile": "example", "action": "analyze"})[1]["task_id"]
        started.wait(5)
        # чужой профиль видит только «занято»: ни названия, ни лога, и остановить не может
        other = self.tasks("other")[0]
        self.assertEqual((other["status"], other["foreign"], other["title"], other["log"]),
                         ("running", True, "Задача другого профиля", []))
        self.assertEqual(self.call("/api/jobs")[1]["tasks"][0]["foreign"], True)          # без профиля — тоже чужая
        self.assertEqual(self.call("/api/stop", {"profile": "other", "task_id": tid})[0], 400)
        mine = self.tasks()[0]
        self.assertEqual((mine["foreign"], mine["title"].startswith("Разбор")), (False, True))
        self.call("/api/stop", {"profile": "example", "task_id": tid})
        job = self.wait_job()
        self.assertTrue(job["stopped"])
        self.assertEqual(job["error"], "")
        analyzed = [r for r in self.call("/api/state?profile=example")[1]["rows"] if r["analyzed"]]
        self.assertEqual(len(analyzed), 1)                                          # первая доделана и сохранена

    def test_queue_rules(self):
        """Пачка профиля — одна за раз; одиночные встают в очередь и идут между вакансиями пачки;
        модель и профиль не меняются, пока у профиля есть задачи."""
        for n in range(1, 4):
            self.t.add_vacancy(n, f"ИТ-директор {n}")
        started = threading.Event()

        def slow_model(prompt, *args):
            started.set()
            time.sleep(0.3)
            return fake_model(prompt, *args)
        self.app.ask = slow_model
        batch = self.call("/api/run", {"profile": "example", "action": "analyze"})[1]["task_id"]
        started.wait(5)
        code, err = self.call("/api/run", {"profile": "example", "action": "update"})
        self.assertEqual(code, 400)                                                  # вторая пачка — нет
        code, single = self.call("/api/run", {"profile": "example", "action": "refresh_card", "n": 3})
        self.assertEqual((code, single["position"]), (200, 1))                       # одиночная — да, первой
        self.assertEqual(self.call("/api/run", {"profile": "example", "action": "refresh_card", "n": 3})[0], 400)
        for path, body in (("/api/cloud", {"enabled": True, "consent": True}), ("/api/profile/update", {"answers": {}})):
            code, err = self.call(path, {"profile": "example", **body})
            self.assertEqual(code, 400, path)
            self.assertIn("задач", str(err), path)                                    # мешают задачи профиля
        self.wait_job()
        done = {t["id"]: t for t in self.tasks()}
        self.assertEqual({done[batch]["status"], done[single["task_id"]]["status"]}, {"done"})
        self.assertLess(done[single["task_id"]]["finished"], done[batch]["finished"])   # не ждала конца пачки

    def test_refresh_and_letter_versions(self):
        p = self.t.profile
        self.t.add_vacancy(1, "ИТ-директор")
        self.t.add_vacancy(2, "CIO")
        self.call("/api/run", {"profile": "example", "action": "analyze"})
        self.assertEqual(self.wait_job()["error"], "")
        for n in (1, 2):                                                              # письма — только кнопкой
            self.call("/api/run", {"profile": "example", "action": "letter", "n": n})
            self.wait_job()
        self.call("/api/status", {"profile": "example", "n": 2, "value": "no"})
        before = {f.name: f.stat().st_mtime for f in p.results.glob("*.md")}
        time.sleep(1.1)                                                               # разное время версий
        self.call("/api/run", {"profile": "example", "action": "refresh", "reanalyze": ["new"], "reletters": ["new"]})
        job = self.wait_job()
        self.assertEqual(job["error"], "")
        after = {f.name: f.stat().st_mtime for f in p.results.glob("*.md")}
        changed = [n for n in after if after[n] != before[n]]
        self.assertEqual([c[:2] for c in changed], ["01"])                           # только «не обработано»
        letters = self.call("/api/vacancy?profile=example&n=1")[1]["letters"]
        self.assertEqual([l["current"] for l in letters], [True, False])             # новая + прежняя в истории
        self.assertEqual(len(self.call("/api/vacancy?profile=example&n=2")[1]["letters"]), 1)
        self.call("/api/run", {"profile": "example", "action": "letter", "n": 2})   # кнопка «новая версия»
        self.wait_job()
        self.assertEqual(len(self.call("/api/vacancy?profile=example&n=2")[1]["letters"]), 2)
        self.assertEqual(len(list(p.letters.glob("*.md"))), 2)                       # в папке писем — только текущие

    def test_no_auto_letters_and_referrer_letter(self):
        p = self.t.profile
        self.t.add_vacancy(1, "ИТ-директор")                                        # 8 и «да» — письмо само не пишется
        self.call("/api/run", {"profile": "example", "action": "analyze"})
        self.wait_job()
        self.assertFalse(self.call("/api/state")[1]["rows"][0]["letter"])
        code, err = self.call("/api/run", {"profile": "example", "action": "referrer_letter", "n": 1})
        self.assertEqual(code, 400)                                                   # референсера ещё нет
        self.assertIn("референсера", err["error"])
        self.call("/api/referrer", {"profile": "example", "n": 1, "text": "Иван Петров, CFO"})
        for channel in ("telegram", "invite"):
            self.call("/api/run", {"profile": "example", "action": "referrer_letter", "n": 1, "channel": channel,
                                   "goal": "learn", "extra": "вместе работали"})
            self.assertEqual(self.wait_job()["error"], "")
        d = self.call("/api/vacancy?profile=example&n=1")[1]
        self.assertEqual([(l["to"], l["channel"], l["current"]) for l in d["ref_letters"]],
                         [("Иван Петров, CFO", "invite", True), ("Иван Петров, CFO", "telegram", False)])
        self.assertIn("Иван", d["ref_letters"][0]["text"])
        self.assertEqual(d["letters"], [])                                           # сопроводительного нет
        self.assertTrue(self.call("/api/state")[1]["rows"][0]["letter"])             # ✉ — есть письмо
        self.assertEqual(len(list(p.letters.glob("*.md"))), 0)                        # сообщения — в своей папке

    def test_calibration(self):
        """Набор калибровки: свои оценки — расхождения первыми, флажок убирает, автонастройка — по набору."""
        for n in range(1, 9):
            self.t.add_vacancy(n, "Начальник отдела ИТ" if n % 2 else "ИТ-директор")   # модель: 3/нет и 8/да
        self.call("/api/run", {"profile": "example", "action": "analyze"})
        self.wait_job()
        st = self.call("/api/calibration?profile=example")[1]
        self.assertEqual((st["rated"], len(st["unrated"]), st["picked"], st["limit"]), ([], 8, [], 8))
        self.assertEqual(self.call("/api/calibration/rate", {"profile": "example", "n": 2, "can": 11, "want": 5,
                                                             "decision": "да"})[0], 400)
        for n in range(1, 8):                                            # я: всё «да» — модель пропустила нечётные
            ratings.set_rating(self.t.profile, n, 7, 7, "да", "подходит | по уровню", today=date(2026, 10, 20 + n))
        st = self.call("/api/calibration?profile=example")[1]
        self.assertEqual(st["picked"], [7, 5, 3, 1, 6, 4, 2])                # расхождения первыми, внутри — свежие
        self.assertEqual([v["n"] for v in st["rated"] if v["diverge"]], [7, 5, 3, 1])
        self.assertEqual(([v["n"] for v in st["unrated"]], st["rated"][0]["reason"]), ([8], "подходит / по уровню"))
        self.call("/api/calibration/select", {"profile": "example", "n": 3, "on": False})     # убрать из набора
        self.assertEqual(self.call("/api/calibration/select", {"profile": "example", "n": 8, "on": True})[1]["picked"],
                         [7, 5, 1, 6, 4, 2])                                  # без своей оценки не добавить
        self.call("/api/run", {"profile": "example", "action": "tune", "rounds": 1})
        self.assertEqual(self.wait_job()["error"], "")
        t = self.call("/api/calibration?profile=example")[1]["tune"]
        self.assertEqual((t["reference"], sorted(r["n"] for r in t["rows"])), (6, [1, 2, 4, 5, 6, 7]))   # только набор
        r1 = next(r for r in t["rows"] if r["n"] == 1)
        self.assertEqual((r1["yes"], r1["before"], r1["after"]["yes"] in (True, False)), (True, {"score": 3, "yes": False}, True))
        self.assertTrue(self.call("/api/state?profile=example")[1]["calibrated"])
        self.call("/api/calibration/select", {"profile": "example", "reset": True})      # «Подобрать заново»
        st = self.call("/api/calibration?profile=example")[1]
        self.assertEqual((st["picked"], st["edited"]), ([7, 5, 3, 1, 6, 4, 2], False))

    def test_setup_wizard(self):
        code, check = self.call("/api/setup/check")
        self.assertEqual((code, check["profiles"], check["default"]), (200, ["example"], "example"))
        answers = {"name": "Анна Иванова", "titles": "Главный бухгалтер", "city": "Москва", "remote": True,
                   "resume": "Резюме", "salary": "200000"}
        preview = self.call("/api/setup/preview", {"answers": answers})[1]
        self.assertIn("от 200 000 ₽", preview["criteria"])
        self.assertEqual((preview["title_words"], preview["level_words"]), ("бухга", "главн"))
        self.assertIn("заместител", preview["stop_words"])                          # для руководящих — по умолчанию
        self.assertIn("Анна Иванова", preview["letter"])
        code, created = self.call("/api/setup/create", {"answers": answers})
        self.assertEqual((code, created["profile"]), (200, "anna"))
        self.assertEqual(self.call("/api/state")[1]["profile"], "anna")              # стал профилем по умолчанию
        self.assertEqual(self.call("/api/setup/resume", {"data": "UEsDBA=="})[0], 400)   # docx — понятная ошибка

    def test_errors_are_shown(self):
        def broken(*args):
            raise A.AssistantError("Ollama не запущена")
        self.app.ask = broken
        self.t.add_vacancy(1, "ИТ-директор")
        self.call("/api/run", {"profile": "example", "action": "analyze"})
        self.assertEqual(self.wait_job()["error"], "Ollama не запущена")
        row = self.call("/api/state?profile=example")[1]["rows"][0]
        self.assertFalse(row["analyzed"])                                            # ждёт разбора


if __name__ == "__main__":
    unittest.main()
