"""Облачная модель GigaChat: настройки, согласие, токен, запросы — без сети (ответы GigaChat подменены)."""
import json
import os
import shutil
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import FIXTURES

from vacancy_assistant import cloud, model, settings
from vacancy_assistant.errors import AssistantError
from vacancy_assistant.profile import Profile

REAL_REQUEST = cloud._request          # до подмены в setUp — чтобы проверить повторы при обрыве связи


class FakeGigaChat:
    """Подмена cloud._request: OAuth выдаёт токен, /models — список, /chat/completions — ответ."""

    def __init__(self):
        self.calls = []

    def __call__(self, url, data=None, headers=None, timeout=60):
        self.calls.append((url, headers or {}, data))
        if url == cloud.OAUTH:
            if "плохой" in headers["Authorization"]:
                raise cloud.CloudHTTPError(401, "Unauthorized")
            return {"access_token": "tok", "expires_at": 4_000_000_000_000}
        if url.endswith("/models"):
            return {"data": [{"id": "GigaChat-2"}, {"id": "GigaChat-2-Pro"}]}
        return {"choices": [{"message": {"content": " Работает "}}]}


class Cloud(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.fake = FakeGigaChat()
        patches = [mock.patch.object(cloud, "_request", self.fake),
                   mock.patch.object(settings, "profiles_dir", lambda: self.root)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        cloud._token.update(key=None, value=None, until=0)
        cloud._base["url"] = None
        for name in ("ivan", "maria"):                                          # два профиля на одном компьютере
            shutil.copytree(FIXTURES / "профили" / "example", self.root / name)
        self.ivan, self.maria = Profile("ivan", self.root), Profile("maria", self.root)
        cloud.use(self.ivan)
        self.addCleanup(cloud.use, None)

    def test_enable_needs_key_and_consent(self):
        with self.assertRaises(AssistantError):
            cloud.save(self.root, True, consent=True, profile=self.ivan)                 # без ключа
        with self.assertRaises(AssistantError):
            cloud.save(self.root, True, auth_key="ключ", profile=self.ivan)              # без согласия
        with self.assertRaises(AssistantError):
            cloud.save(self.root, True, auth_key="плохой", consent=True, profile=self.ivan)   # ключ не принят
        self.assertFalse(cloud.active(self.ivan))

    def test_enabled_cloud_answers_instead_of_ollama(self):
        pub = cloud.save(self.root, True, auth_key="секретный-ключ-1234", consent=True, model="GigaChat-2-Pro",
                         profile=self.ivan)
        self.assertTrue(pub["enabled"])
        self.assertNotIn("auth_key", pub)                                      # ключ в окно не отдаём
        self.assertEqual(pub["key_tail"], "1234")
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE((self.root / cloud.CONFIG).stat().st_mode), 0o600)
        self.assertEqual(model.current_model(), "GigaChat-2-Pro")
        self.assertEqual(model.ask_model("Привет", options={"temperature": 0, "num_predict": 50}), "Работает")
        url, headers, data = self.fake.calls[-1]
        self.assertTrue(url.endswith("/api/v1/chat/completions"))
        self.assertEqual(headers["Authorization"], "Bearer tok")
        self.assertIn(b'"max_tokens": 50', data)
        oauth = sum(1 for u, _, _ in self.fake.calls if u == cloud.OAUTH)
        model.ask_model("Ещё раз")
        self.assertEqual(sum(1 for u, _, _ in self.fake.calls if u == cloud.OAUTH), oauth)   # токен не просим заново

    def test_disable_returns_to_local_model(self):
        cloud.save(self.root, True, auth_key="k", consent=True, profile=self.ivan)
        cloud.save(self.root, False, profile=self.ivan)
        self.assertFalse(cloud.active(self.ivan))
        self.assertEqual(model.current_model(), settings.MODEL)
        self.assertTrue(cloud.public(self.root)["has_key"])                    # ключ сохранён — включить снова просто

    def test_each_profile_has_own_model(self):
        cloud.save(self.root, True, auth_key="k", consent=True, profile=self.ivan)
        self.assertTrue(cloud.active(Profile("ivan", self.root)))
        self.assertFalse(cloud.active(Profile("maria", self.root)))            # ключ общий, выбор — свой
        self.assertFalse(cloud.public(self.root, Profile("maria", self.root))["enabled"])
        cloud.use(Profile("maria", self.root))
        self.assertEqual(model.current_model(), settings.MODEL)
        cloud.use(Profile("ivan", self.root))
        self.assertEqual(model.current_model(), cloud.DEFAULT_MODEL)
        cloud.use(None)                                                         # профиля нет — локальная
        self.assertEqual(model.current_model(), settings.MODEL)

    def test_old_shared_setting_goes_to_every_profile(self):
        (self.root / cloud.CONFIG).write_text(json.dumps({"auth_key": "k", "enabled": True, "consent": True}),
                                              encoding="utf-8")
        self.assertTrue(cloud.active(Profile("maria", self.root)))             # прежний выбор — пока общий
        cloud.save(self.root, False, profile=Profile("ivan", self.root))        # Иван вернулся к локальной
        self.assertFalse(cloud.active(Profile("ivan", self.root)))
        self.assertTrue(cloud.active(Profile("maria", self.root)))             # у Марии облако осталось
        self.assertNotIn("enabled", json.loads((self.root / cloud.CONFIG).read_text(encoding="utf-8")))

    def test_falls_back_when_main_address_fails(self):
        def flaky(url, data=None, headers=None, timeout=60):
            if url.startswith(cloud.BASES[0]):
                raise cloud.CloudNetError("timeout")                            # новый адрес не отвечает
            return self.fake(url, data, headers, timeout)
        with mock.patch.object(cloud, "_request", flaky):
            cloud.save(self.root, True, auth_key="k", consent=True, profile=self.ivan)
            self.assertEqual(model.ask_model("Привет"), "Работает")
        self.assertEqual(cloud._base["url"], cloud.BASES[1])                   # запомнил рабочий адрес

    def test_retries_short_network_drops(self):
        drops = {"left": 2}

        def once(url, data=None, headers=None, timeout=60):
            if drops["left"]:
                drops["left"] -= 1
                raise cloud.CloudNetError("timeout")
            return {"ok": True}
        with mock.patch.object(cloud, "_request_once", once), mock.patch.object(cloud.time, "sleep", lambda s: None):
            self.assertEqual(REAL_REQUEST("https://example"), {"ok": True})        # два обрыва — третий раз удачно
            drops["left"] = cloud.NET_RETRIES
            with self.assertRaises(cloud.CloudNetError):
                REAL_REQUEST("https://example")                                    # сеть пропала надолго — ошибка

    def test_unknown_model_is_reported(self):
        with self.assertRaises(AssistantError) as e:
            cloud.save(self.root, True, auth_key="k", consent=True, model="GigaChat-Ultra")
        self.assertIn("GigaChat-2-Pro", str(e.exception))                      # подсказка: что доступно

    def test_certificates_are_bundled(self):
        text = cloud.CA_FILE.read_text(encoding="utf-8")
        self.assertEqual(text.count("BEGIN CERTIFICATE"), 2)
        cloud._context()                                                        # загружаются без ошибок


if __name__ == "__main__":
    unittest.main()
