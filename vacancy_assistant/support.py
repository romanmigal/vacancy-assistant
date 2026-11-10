"""Журнал ошибок и сведения для поддержки.

- Журнал — журнал.txt в папке данных. Установленная программа пишет туда весь свой вывод (desktop.py); ошибки
  сервера и окна пишутся туда всегда — и когда программа запущена из терминала.
- При запуске журнал обрезается: остаётся последний мегабайт.
- «Скопировать сведения для поддержки» (О программе): версия, система, модель и последние строки журнала —
  без резюме и вакансий (их в журнале нет), без ключей, почты и ссылок входа hh (loginkey).
"""
import platform
import re
import sys
import threading
import traceback
from datetime import datetime

from . import __version__, settings

LOG_NAME = "журнал.txt"
KEEP = 1_000_000                       # столько байт журнала остаётся после обрезки
TAIL = 80                              # строк журнала в сведениях для поддержки
_LOCK = threading.Lock()

HIDE = [
    (re.compile(r"\S*loginkey\S*", re.I), "[ссылка входа скрыта]"),           # ссылки входа hh — целиком
    (re.compile(r"(?i)(auth_key|authorization|token|ключ|key|password|пароль)(\W{1,3})\S+"), r"\1\2[скрыто]"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[почта скрыта]"),
    (re.compile(r"\b[A-Za-z0-9+/=_-]{32,}\b"), "[скрыто]"),                     # длинные ключи и токены
    (re.compile(r"(?:\+7|\b8)[\s(-]*\d{3}[\s)-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}\b"), "[телефон скрыт]"),
]


def log_path():
    return settings.data_root() / LOG_NAME


def _to_file():
    """Вывод программы уже идёт в журнал (установленная программа) — писать в файл ещё раз не нужно."""
    return getattr(sys.stderr, "name", "").endswith(LOG_NAME)


def log(text):
    """Строка в журнал с датой и временем."""
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {text.rstrip()}\n"
    with _LOCK:
        if _to_file():
            sys.stderr.write(line)
            sys.stderr.flush()
            return
        try:
            with open(log_path(), "a", encoding="utf-8") as f:
                f.write(line)
            return
        except OSError:
            pass
        try:                                        # в файл не вышло — хотя бы в консоль
            sys.stderr.write(line)
        except (OSError, ValueError, AttributeError):
            pass


def log_error(where, error=None):
    """Ошибка с трассировкой — в журнал (вызывать внутри except)."""
    log(f"Ошибка: {where}\n{traceback.format_exc() if error is None else ''.join(traceback.format_exception(error))}")


def trim(path=None, keep=KEEP):
    """Журнал больше keep байт — оставляем последние keep, с начала строки."""
    path = path or log_path()
    try:
        if not path.exists() or path.stat().st_size <= keep:
            return
        with open(path, "rb") as f:
            f.seek(-keep, 2)
            data = f.read()
        data = data[data.find(b"\n") + 1:]
        with open(path, "wb") as f:
            f.write("[... начало журнала обрезано ...]\n".encode("utf-8") + data)
    except OSError:
        pass


def hide(text):
    """Без ключей, почты, телефонов и ссылок входа hh."""
    for rx, repl in HIDE:
        text = rx.sub(repl, text)
    return text


def tail(path=None, lines=TAIL):
    path = path or log_path()
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return "".join(f.readlines()[-lines:])
    except OSError:
        return ""


def info(model="", machine="", profiles=0):
    """Сведения для поддержки — текстом, чтобы вставить в письмо или чат."""
    log_text = tail()
    return hide("\n".join([
        f"Помощник по вакансиям {__version__}",
        f"Система: {platform.system()} {platform.release()} ({platform.machine()}), Python {platform.python_version()}"
        f"{', установленная программа' if getattr(sys, 'frozen', False) else ', из исходников'}",
        f"Модель: {model or '—'}",
        f"Компьютер: {machine}" if machine else "",
        f"Профилей: {profiles}",
        "",
        f"Последние строки журнала ({LOG_NAME}):" if log_text else "Журнал пуст.",
        log_text.rstrip(),
    ]))
