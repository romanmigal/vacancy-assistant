"""Установленная программа на Mac: корневые сертификаты macOS вместо отсутствующего cert.pem с машины сборки."""
import os
import shutil
import ssl
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from helpers import PROJECT  # noqa: F401  (путь к пакету)

from vacancy_assistant import desktop

PEM = "-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n"
NO_PATHS = ssl.DefaultVerifyPaths("/нет/cert.pem", "/нет/certs", "SSL_CERT_FILE", "/нет/cert.pem", "SSL_CERT_DIR", "/нет/certs")


class Roots(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.env = mock.patch.dict(os.environ, {}, clear=False)
        self.env.start()
        os.environ.pop("SSL_CERT_FILE", None)

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.dir, ignore_errors=True)

    def run_(self, *a, **k):
        return SimpleNamespace(returncode=0, stdout=PEM)

    @mock.patch.object(desktop.sys, "platform", "darwin")
    def test_frozen_without_cafile(self):
        with mock.patch.object(desktop.ssl, "get_default_verify_paths", return_value=NO_PATHS):
            pem = desktop.use_system_roots(self.dir, run=self.run_)
        self.assertEqual(os.environ["SSL_CERT_FILE"], str(pem))
        self.assertIn("BEGIN CERTIFICATE", pem.read_text())

    @mock.patch.object(desktop.sys, "platform", "darwin")
    def test_security_fails_uses_previous_file(self):
        (self.dir / "корневые сертификаты.pem").write_text(PEM)
        with mock.patch.object(desktop.ssl, "get_default_verify_paths", return_value=NO_PATHS):
            pem = desktop.use_system_roots(self.dir, run=lambda *a, **k: SimpleNamespace(returncode=1, stdout=""))
        self.assertEqual(os.environ["SSL_CERT_FILE"], str(pem))

    @mock.patch.object(desktop.sys, "platform", "darwin")
    def test_python_with_certs_untouched(self):
        cafile = self.dir / "cert.pem"
        cafile.write_text(PEM)
        paths = ssl.DefaultVerifyPaths(str(cafile), None, "SSL_CERT_FILE", str(cafile), "SSL_CERT_DIR", "")
        with mock.patch.object(desktop.ssl, "get_default_verify_paths", return_value=paths):
            self.assertIsNone(desktop.use_system_roots(self.dir, run=lambda *a, **k: self.fail("не нужно")))
        self.assertNotIn("SSL_CERT_FILE", os.environ)

    def test_not_mac(self):
        with mock.patch.object(desktop.sys, "platform", "win32"):
            self.assertIsNone(desktop.use_system_roots(self.dir, run=lambda *a, **k: self.fail("не нужно")))

    @unittest.skipUnless(sys.platform == "darwin", "только на Mac")
    def test_real_keychain(self):
        """Настоящий системный набор корневых сертификатов macOS выгружается и подходит для ssl."""
        with mock.patch.object(desktop.ssl, "get_default_verify_paths", return_value=NO_PATHS):
            pem = desktop.use_system_roots(self.dir)
        ctx = ssl.create_default_context(cafile=str(pem))
        self.assertGreater(len(ctx.get_ca_certs()), 50)


if __name__ == "__main__":
    unittest.main()
