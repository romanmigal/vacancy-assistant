"""Запуск как обычной программы (из установщика): двойной щелчок — и открывается окно в браузере.

Данные пользователя — в папке «Документы/Помощник по вакансиям» (её удобно открыть и в Obsidian).
При первом запуске туда кладётся профиль-пример. Если программа уже запущена, второй запуск
просто открывает её окно. Вывод программы пишется в журнал.txt в той же папке: у программы нет консоли.
"""
import os
import ssl
import subprocess
import sys
import urllib.request
import webbrowser
from pathlib import Path

from . import datadir, settings
from .app import PORT

APP_NAME = "Помощник по вакансиям"


def user_home():
    """Папка данных: заданная при запуске, выбранная в настройках или «Документы/Помощник по вакансиям»."""
    return Path(os.environ.get("VACANCY_ASSISTANT_HOME") or datadir.saved() or Path.home() / "Documents" / APP_NAME)


def prepare(home):
    """Папка данных; профилей в ней пока нет — первый создаст мастер в окне."""
    (home / "профили").mkdir(parents=True, exist_ok=True)


ROOTS = "/System/Library/Keychains/SystemRootCertificates.keychain"


def use_system_roots(cache_dir, run=subprocess.run):
    """Mac: Python в собранной программе ищет корневые сертификаты по пути с машины сборки
    (/Library/Frameworks/Python.framework/…/cert.pem), а у пользователя его нет — и любой https
    (hh.ru, сайты вакансий, проверка обновлений, курс ЦБ) падает на проверке сертификата.
    Берём корневые сертификаты macOS в файл и указываем его через SSL_CERT_FILE. → путь к файлу или None."""
    if sys.platform != "darwin" or os.environ.get("SSL_CERT_FILE"):
        return None
    paths = ssl.get_default_verify_paths()
    if (paths.cafile and os.path.exists(paths.cafile)) or (paths.capath and os.path.isdir(paths.capath) and os.listdir(paths.capath)):
        return None                                     # Python со своими сертификатами — ничего не нужно
    pem = Path(cache_dir) / "корневые сертификаты.pem"
    try:
        r = run(["security", "find-certificate", "-a", "-p", ROOTS], capture_output=True, text=True, timeout=30)
        if r.returncode == 0 and "BEGIN CERTIFICATE" in r.stdout:
            pem.parent.mkdir(parents=True, exist_ok=True)
            pem.write_text(r.stdout, encoding="ascii")
    except (OSError, subprocess.SubprocessError):
        pass                                            # нет — возьмём прежний файл, если он есть
    if not pem.exists():
        return None
    os.environ["SSL_CERT_FILE"] = str(pem)
    return pem


def running_url(port=PORT):
    """Адрес окна, если программа уже запущена на этом компьютере, иначе None."""
    url = f"http://127.0.0.1:{port}/"
    try:
        with urllib.request.urlopen(url, timeout=2) as r:
            return url if r.headers.get("Server", "").startswith("VacancyAssistant") else None
    except OSError:
        return None


def self_check():
    """Проверка собранной программы при сборке (build_mac.sh): https открывается — сертификаты на месте."""
    import tempfile
    use_system_roots(tempfile.mkdtemp())
    from . import updates
    try:
        print("https: ok, последняя версия", updates.fetch_latest().get("version"))
        return 0
    except Exception as e:                              # noqa: BLE001
        print("https: ошибка —", e)
        return 1


def main():
    if "--self-check" in sys.argv:
        sys.exit(self_check())
    home = user_home()
    os.environ["VACANCY_ASSISTANT_HOME"] = str(home)
    prepare(home)
    log = open(home / "журнал.txt", "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = log                       # у программы без консоли stdout нет
    if use_system_roots(datadir.config_dir()):
        print("Сертификаты: корневые сертификаты macOS")
    url = running_url()
    if url:
        print("Программа уже запущена — открываю окно.")
        webbrowser.open(url)
        return
    from .app import serve
    serve(open_browser=True)


if __name__ == "__main__":
    main()
