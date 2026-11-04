"""Чтение и запись текстовых файлов одинаково на Mac и Windows.

Всегда UTF-8 и переводы строк «\\n»: иначе Windows пишет «\\r\\n», и при синхронизации папки
между Mac и Windows файлы «меняются» на каждом компьютере, хотя содержимое то же.

Запись — через временный файл, который затем подменяет старый одним действием: если программа
упадёт или компьютер выключится посреди записи, останется прежний файл, а не пустой.
"""
import json
import os
import threading
import time
from pathlib import Path


def read_text(path):
    with open(path, encoding="utf-8", newline=None) as f:        # «\r\n» при чтении → «\n»
        return f.read()


def write_text(path, text):
    path = Path(path)
    # Имя с точкой — Obsidian и проводник его не показывают; pid и поток — чтобы записи не мешали друг другу
    tmp = path.with_name(f".{path.name}.{os.getpid()}-{threading.get_ident()}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        for attempt in range(5):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:                # Windows: файл на миг занят (антивирус, Obsidian) — повторим
                if attempt == 4:
                    raise
                time.sleep(0.1 * (attempt + 1))
    finally:
        if tmp.exists():
            tmp.unlink()


def append_text(path, text):
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(text)


def read_json(path, default=None):
    """JSON-файл программы; если файла нет — default."""
    return json.loads(read_text(path)) if Path(path).exists() else default


def write_json(path, data):
    """Все JSON программы — в одном виде: русские буквы как есть, отступ 2, перевод строки в конце."""
    write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def log_print(message=""):
    """Вывод по умолчанию для параметра log: печать сразу, без буфера."""
    print(message, flush=True)


__all__ = ["Path", "read_text", "write_text", "append_text", "read_json", "write_json", "log_print"]
