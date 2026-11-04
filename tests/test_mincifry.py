"""Сайты с сертификатом Минцифры: после ошибки «неизвестный издатель» — повтор с сертификатами
Минцифры; другие ошибки сертификата так не обходятся."""
import io
import ssl
import unittest
import urllib.error
from unittest import mock

from vacancy_assistant import sites
from vacancy_assistant.errors import AssistantError


def cert_error(code, text):
    e = ssl.SSLCertVerificationError(1, f"certificate verify failed: {text}")
    e.verify_code = code
    return urllib.error.URLError(e)


class Response(io.BytesIO):
    headers = type("H", (), {"get_content_charset": lambda self: "utf-8"})()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class Mincifry(unittest.TestCase):
    def test_retry_with_mincifry(self):
        calls, lines = [], []

        def urlopen(request, timeout=None, context=None):
            calls.append(context)
            if context is None:
                raise cert_error(20, "unable to get local issuer certificate")
            return Response("<html>вакансия</html>".encode())
        with mock.patch.object(sites.urllib.request, "urlopen", urlopen):
            page = sites.fetch("https://royal-bank.example/", log=lines.append)
        self.assertEqual(page, "<html>вакансия</html>")
        self.assertEqual((calls[0], calls[1]), (None, sites.mincifry_context()))     # сначала обычная проверка
        self.assertIs(sites.mincifry_context(), sites.mincifry_context())            # контекст — один на всё
        self.assertIn("сертификатом Минцифры", lines[0])

    def test_other_cert_errors_not_bypassed(self):
        calls = []

        def urlopen(request, timeout=None, context=None):
            calls.append(context)
            raise cert_error(10, "certificate has expired")
        with mock.patch.object(sites.urllib.request, "urlopen", urlopen):
            with self.assertRaises(AssistantError):
                sites.fetch("https://old.example/", log=lambda *_: None)
        self.assertEqual(calls, [None, None])                                         # обычные попытки, без Минцифры

    def test_still_untrusted(self):
        def urlopen(request, timeout=None, context=None):
            raise cert_error(20, "unable to get local issuer certificate")
        with mock.patch.object(sites.urllib.request, "urlopen", urlopen):
            with self.assertRaisesRegex(AssistantError, "сохранённой страницей или текстом"):
                sites.fetch("https://strange.example/", log=lambda *_: None)


if __name__ == "__main__":
    unittest.main()
