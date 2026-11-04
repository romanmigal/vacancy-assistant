"""Текст из буфера обмена — на Mac, Windows и Linux."""
import shutil
import subprocess
import sys


def clipboard_text():
    """Возвращает текст из буфера обмена или '' если прочитать не удалось."""
    commands = []
    if sys.platform == "darwin":
        commands.append(["pbpaste"])
    elif sys.platform.startswith("win"):
        commands.append(["powershell", "-NoProfile", "-Command",
                         "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-Clipboard -Raw"])
    else:
        for cmd in (["wl-paste", "-n"], ["xclip", "-selection", "clipboard", "-o"], ["xsel", "-b", "-o"]):
            if shutil.which(cmd[0]):
                commands.append(cmd)
    for cmd in commands:
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=10)
            if r.returncode == 0:
                return r.stdout.decode("utf-8", errors="replace")
        except (OSError, subprocess.SubprocessError):
            pass
    try:                                    # запасной путь — tkinter из стандартной библиотеки
        import tkinter
        root = tkinter.Tk()
        root.withdraw()
        try:
            return root.clipboard_get()
        finally:
            root.destroy()
    except Exception:
        return ""
