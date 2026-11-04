"""Скрипты окна — обычные файлы, которые видят функции друг друга: вызов функции, которой нет ни в одном
из них, ломает кнопку только при нажатии (так «Поставить свои оценки» потеряла decWord после переделки калибровки)."""
import re
import unittest
from pathlib import Path

JS = Path(__file__).resolve().parent.parent / "vacancy_assistant" / "web" / "js"
BUILTINS = set("""if for while switch catch function return typeof new await async Math JSON Object Array String Number Boolean
Date Set Map Promise setTimeout clearTimeout setInterval clearInterval fetch encodeURIComponent decodeURIComponent parseInt
parseFloat isNaN isFinite alert confirm prompt requestAnimationFrame URL URLSearchParams Blob FileReader FormData Error RegExp
structuredClone Intl open atob btoa queueMicrotask getComputedStyle matchMedia Symbol WeakMap Event CustomEvent super import
addEventListener scrollTo Uint8Array""".split())
NOT_CALLS = {"GigaChat"}          # «… в GigaChat (Сбер)» во вложенном шаблоне строки — не вызов


class Names(unittest.TestCase):
    def test_called_functions_exist(self):
        src = "\n".join(f.read_text(encoding="utf-8") for f in sorted(JS.glob("*.js")))
        code = re.sub(r"//[^\n]*", "", src)
        code = re.sub(r"`(?:\\.|[^`\\])*`|\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'", '""', code)
        defined = set(re.findall(r"\bfunction\s+([A-Za-z_$][\w$]*)", src))
        defined |= set(re.findall(r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=", src))
        params = set()
        for m in re.finditer(r"\(([^()]*)\)\s*=>|function\s*[\w$]*\s*\(([^()]*)\)|([A-Za-z_$][\w$]*)\s*=>", src):
            for g in m.groups():
                if g:
                    params |= set(re.findall(r"[A-Za-z_$][\w$]*", g))
        called = set(re.findall(r"(?<![\w$.])([A-Za-z_$][\w$]*)\s*\(", code))
        self.assertEqual(sorted(called - defined - params - BUILTINS - NOT_CALLS), [])


if __name__ == "__main__":
    unittest.main()
