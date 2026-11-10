"""Понятные ошибки: сервер, окно, испорченный файл; журнал и сведения для поддержки."""
import json
import threading
import unittest
import urllib.error
import urllib.request

from helpers import TEST_LOG, TempProfile, fake_model

from vacancy_assistant import app as A, support
from vacancy_assistant.errors import AssistantError
from vacancy_assistant.textio import read_json, write_text


@A.route("/api/test-boom", profile=False)
def _boom(app, p, a):
    if a.get("kind") == "key":
        return {}["n"]
    if a.get("kind") == "value":
        return int("abc")
    raise RuntimeError("искусственная ошибка")


class Errors(unittest.TestCase):
    def setUp(self):
        self.t = TempProfile().__enter__()
        self.app = A.App(self.t.profiles, ask=fake_model, check=lambda: {"ollama": True, "model_ok": True, "memory_gb": 16})
        self.server = A.make_server(self.app, port=0)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        TEST_LOG.write_text("", encoding="utf-8")

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.t.__exit__()

    def call(self, path, body=None):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"X-Token": self.app.token, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def test_route_error(self):
        """Ошибка в маршруте — ответ с понятным текстом, трассировка — в журнал; соединение не рвётся."""
        code, res = self.call("/api/test-boom")
        self.assertEqual(code, 500)
        self.assertIn("Внутренняя ошибка программы", res["error"])
        log = TEST_LOG.read_text(encoding="utf-8")
        self.assertIn("GET /api/test-boom", log)
        self.assertIn("RuntimeError: искусственная ошибка", log)
        self.assertEqual(self.call("/api/test-boom?kind=key"),
                         (400, {"error": "В запросе не хватает данных (n) — обновите окно и повторите."}))
        self.assertEqual(self.call("/api/test-boom?kind=value")[0], 400)

    def test_client_error_logged_without_secrets(self):
        self.assertEqual(self.call("/api/client-error", {"message": "TypeError: x is undefined https://hh.ru/a?loginkey=SECRET1",
                                                         "where": "main.js:10:5"})[0], 200)
        log = TEST_LOG.read_text(encoding="utf-8")
        self.assertIn("Ошибка в окне: TypeError: x is undefined", log)
        self.assertNotIn("SECRET1", log)

    def test_broken_json(self):
        f = self.t.profile.dir / "контакты.json"
        write_text(f, "{испорчен")
        with self.assertRaises(AssistantError) as e:
            read_json(f)
        self.assertIn("«контакты.json» испорчен", str(e.exception))

    def test_support_info(self):
        support.log("auth_key: abc123 почта ivan@example.com, телефон +7 999 123-45-67, https://hh.ru/x?loginkey=QQQ")
        code, res = self.call("/api/support")
        self.assertEqual(code, 200)
        text = res["text"]
        self.assertIn("Помощник по вакансиям", text)
        self.assertIn("память 16 ГБ", text)
        for secret in ("abc123", "ivan@example.com", "999 123", "QQQ"):
            self.assertNotIn(secret, text)

    def test_trim(self):
        TEST_LOG.write_text("старая строка\n" * 1000 + "последняя\n", encoding="utf-8")
        support.trim(TEST_LOG, keep=500)
        text = TEST_LOG.read_text(encoding="utf-8")
        self.assertLess(len(text.encode("utf-8")), 600)
        self.assertTrue(text.startswith("[... начало журнала обрезано ...]\nстарая строка\n"))
        self.assertTrue(text.endswith("последняя\n"))


if __name__ == "__main__":
    unittest.main()
