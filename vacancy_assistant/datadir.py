"""Папка с данными программы — её можно сменить (Настройки → «Папка с данными», мастер первого запуска).

В папке данных лежат «профили/» (профили, ключ GigaChat, пароль домашней сети, настройка обновлений),
«копии/» и журнал. Какую папку брать, запоминается вне её — в файле настроек пользователя:
    Mac — ~/Library/Application Support/Помощник по вакансиям/папка данных.json,
    Windows — %APPDATA%\\Помощник по вакансиям\\папка данных.json, иначе — ~/.config/…
Порядок: переменная VACANCY_ASSISTANT_HOME (явно задана при запуске) → этот файл → папка по умолчанию.
Модуль не импортирует settings — settings берёт отсюда сохранённую папку.
"""
import os
import subprocess
import sys
from pathlib import Path

APP_NAME = "Помощник по вакансиям"
POINTER = "папка данных.json"
CONFIG_ENV = "VACANCY_ASSISTANT_CONFIG"      # другая папка для файла-указателя — в тестах
PROFILES = "профили"
CONFIG_FILE = "профиль.json"                 # признак папки профиля (как в profile.py)


def config_dir():
    if os.environ.get(CONFIG_ENV):
        return Path(os.environ[CONFIG_ENV])
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA") or Path.home()) / APP_NAME
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / APP_NAME


def saved():
    """Папка, выбранная пользователем, или None."""
    import json
    try:
        home = json.loads((config_dir() / POINTER).read_text(encoding="utf-8")).get("home")
    except (OSError, ValueError, AttributeError):
        return None
    return Path(home) if home else None


def remember(home):
    import json
    folder = config_dir()
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / (POINTER + ".tmp")
    tmp.write_text(json.dumps({"home": str(home)}, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, folder / POINTER)


def profiles_in(folder):
    folder = Path(folder)
    if not folder.is_dir():
        return []
    return sorted(p.name for p in folder.iterdir() if (p / CONFIG_FILE).is_file())


def inspect(path):
    """Что в выбранной папке: {"home": корень данных, "profiles": […], "problem": ""}.
    Выбрали саму «профили» — корень на уровень выше. Папка с профилями прямо внутри (без «профили/») —
    так программа их не увидит: подсказка выбрать или назвать иначе."""
    raw = str(path or "").strip().strip('"')
    if not raw:
        return {"home": "", "profiles": [], "problem": "Укажите папку."}
    home = Path(raw).expanduser()
    if not home.is_absolute():
        return {"home": raw, "profiles": [], "problem": "Нужен полный путь к папке, например /Users/имя/Documents/Вакансии."}
    if not home.is_dir():
        return {"home": str(home), "profiles": [], "problem": "Такой папки нет."}
    if home.name == PROFILES and profiles_in(home):
        home = home.parent
    found = profiles_in(home / PROFILES)
    if not found and profiles_in(home):
        return {"home": str(home), "profiles": [], "problem": f"Профили лежат прямо в этой папке, а программа ищет их в папке «{PROFILES}» внутри. "
                f"Положите их в «{PROFILES}» или выберите папку, где «{PROFILES}» уже есть."}
    if not os.access(home, os.W_OK):
        return {"home": str(home), "profiles": found, "problem": "В эту папку нельзя записывать — выберите другую."}
    return {"home": str(home), "profiles": found, "problem": ""}


def pick(prompt="Папка с данными программы"):
    """Системное окно выбора папки → путь или None (отменили или окна нет — тогда путь вводят вручную)."""
    try:
        if sys.platform == "darwin":
            r = subprocess.run(["osascript", "-e", f'POSIX path of (choose folder with prompt "{prompt}")'],
                               capture_output=True, text=True, timeout=600)
        elif sys.platform == "win32":
            script = ("Add-Type -AssemblyName System.Windows.Forms; $d = New-Object System.Windows.Forms.FolderBrowserDialog; "
                      f"$d.Description = '{prompt}'; if ($d.ShowDialog() -eq 'OK') {{ $d.SelectedPath }}")
            r = subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", script], capture_output=True, text=True, timeout=600)
        else:
            r = subprocess.run(["zenity", "--file-selection", "--directory", f"--title={prompt}"],
                               capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.SubprocessError):
        return None
    path = r.stdout.strip().rstrip("/\\")
    return path if r.returncode == 0 and path else None
