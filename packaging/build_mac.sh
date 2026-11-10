#!/bin/bash
# Сборка для Mac: программа (PyInstaller) и образ диска .dmg с ярлыком «Программы» и инструкцией.
# Запуск из папки проекта:  bash packaging/build_mac.sh   (нужен pip install pyinstaller pypdf)
set -euo pipefail
ARCH=$(uname -m)                                  # arm64 — Apple Silicon (M1…), x86_64 — Intel
NAME="Помощник по вакансиям"
pyinstaller --noconfirm --clean --distpath dist --workpath build packaging/vacancy_assistant.spec
# Имена файлов с «й», «ё» (docs/, шаблоны) — в форме NFD, как их хранит образ диска (HFS+), и подпись заново.
# Иначе подпись помнит одну форму имени, а на диске другая — macOS пишет «программа повреждена».
python3 - "dist/$NAME.app" <<'PY'
import os, sys, unicodedata
for root, dirs, files in os.walk(sys.argv[1], topdown=False):
    for name in files + dirs:
        nfd = unicodedata.normalize("NFD", name)
        if nfd != name:
            os.rename(os.path.join(root, name), os.path.join(root, nfd))
PY
"dist/$NAME.app/Contents/MacOS/VacancyAssistant" --self-check   # пробный запуск: окно, скрипты, шаблоны, «Помощь», https
codesign --force --deep --sign - "dist/$NAME.app"
codesign --verify --deep --strict "dist/$NAME.app"
rm -rf dist/dmg && mkdir -p dist/dmg
cp -R "dist/$NAME.app" dist/dmg/
ln -s /Applications dist/dmg/Applications
cp "packaging/Как установить на Mac.txt" dist/dmg/
DMG="dist/VacancyAssistant-mac-$ARCH.dmg"
rm -f "$DMG"
# На машинах GitHub hdiutil иногда отвечает «Resource busy» — повторяем с паузой
for try in 1 2 3 4 5; do
  hdiutil create -volname "$NAME" -srcfolder dist/dmg -ov -format UDZO "$DMG" && break
  [ "$try" = 5 ] && { echo "Не удалось создать образ .dmg"; exit 1; }
  echo "hdiutil не создал образ, повтор через $((try * 5)) с…"; sleep $((try * 5))
done
# Проверка: программа из готового образа — с целой подписью (как её увидит пользователь)
MNT=$(mktemp -d)
hdiutil attach -nobrowse -readonly -mountpoint "$MNT" "$DMG" >/dev/null
codesign --verify --deep --strict "$MNT/$NAME.app" || { hdiutil detach "$MNT" >/dev/null; echo "Подпись программы в образе нарушена"; exit 1; }
hdiutil detach "$MNT" >/dev/null
rm -rf dist/dmg   # ссылка на /Applications в рабочей папке ломает Obsidian (сканирует все программы)
echo "Готово: $DMG"
