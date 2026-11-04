# Сборка программы PyInstaller'ом:  pyinstaller packaging/vacancy_assistant.spec  (из папки проекта)
# Mac — «Помощник по вакансиям.app», Windows — папка с VacancyAssistant.exe (её упаковывает Inno Setup).
import re
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent
VERSION = re.search(r'__version__ = "([^"]+)"', (ROOT / "vacancy_assistant" / "__init__.py").read_text(encoding="utf-8")).group(1)
datas = [(str(ROOT / "шаблоны"), "шаблоны"),
         (str(ROOT / "vacancy_assistant" / "web"), "vacancy_assistant/web"),
         (str(ROOT / "vacancy_assistant" / "certs"), "vacancy_assistant/certs"),         # сертификаты Минцифры для GigaChat
         (str(ROOT / "vacancy_assistant" / "ссылки.json"), "vacancy_assistant")]    # «Где искать вакансии»
# Образцы резюме и критериев для мастера (вымышленный человек); профилей в программе нет — их создаёт мастер
datas += [(str(ROOT / "примеры" / f), "примеры") for f in ("резюме.md", "критерии.txt")]
datas += [(str(ROOT / "README.md"), "."), (str(ROOT / "docs"), "docs")]       # «Параметры → Помощь»
datas += [(str(ROOT / "LICENSE"), ".")]                                         # GPL-3.0 — текст лицензии рядом с программой

a = Analysis([str(ROOT / "packaging" / "launcher.py")], pathex=[str(ROOT)], datas=datas,
             hiddenimports=["pypdf"], excludes=["tkinter", "unittest", "test"])
pyz = PYZ(a.pure)
mac = sys.platform == "darwin"
ICON = str(ROOT / "packaging" / "icon" / ("icon.icns" if mac else "icon.ico"))   # лупа над вакансией; исходник — icon/*.svg
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="VacancyAssistant",
          console=False, icon=ICON, argv_emulation=False)
coll = COLLECT(exe, a.binaries, a.datas, name="VacancyAssistant")
if mac:
    app = BUNDLE(coll, name="Помощник по вакансиям.app", bundle_identifier="app.vacancy-assistant", icon=ICON,
                 info_plist={"CFBundleDisplayName": "Помощник по вакансиям", "CFBundleShortVersionString": VERSION,
                             "LSUIElement": False, "NSHighResolutionCapable": True})
