#!/bin/bash
# Установка и обновление на Mac одной командой в Терминале:
#   curl -fsSL https://raw.githubusercontent.com/romanmigal/vacancy-assistant/main/packaging/install_mac.sh | bash
# Скачивает .dmg последнего релиза под процессор этого Mac, сверяет SHA-256 с GitHub и копирует программу в «Программы».
# Файл, скачанный curl, не получает метку карантина — macOS не останавливает неподписанную у Apple программу
# и не нужно идти в «Конфиденциальность и безопасность». Прежняя версия программы уходит в Корзину, данные не трогаются.
# Для проверки: VACANCY_ASSISTANT_APPS — другая папка вместо «Программ», VACANCY_ASSISTANT_NO_OPEN=1 — не запускать.
set -euo pipefail

NAME="Помощник по вакансиям"
REPO="romanmigal/job-search-assistant-releases"

say() { printf '%s\n' "$*"; }
die() { printf 'Ошибка: %s\n' "$*" >&2; exit 1; }

# Всё — внутри функции: bash читает скрипт из curl по частям, а так он целиком прочитан до первой команды
main() {
  [ "$(uname -s)" = Darwin ] || die "этот установщик — для Mac. Для Windows скачайте установщик со страницы https://github.com/$REPO/releases/latest"
  local arch
  arch=$(uname -m)                                       # arm64 — Apple Silicon, x86_64 — Intel
  [ "$(sysctl -n sysctl.proc_translated 2>/dev/null || true)" = 1 ] && arch=arm64   # Терминал под Rosetta на Apple Silicon
  local file="VacancyAssistant-mac-$arch.dmg"

  if pgrep -x VacancyAssistant >/dev/null 2>&1; then
    die "программа запущена. Закройте её: «Параметры» (шестерёнка) → «Выйти из программы» — и выполните команду снова."
  fi

  local dir="${VACANCY_ASSISTANT_APPS:-/Applications}"
  if [ -z "${VACANCY_ASSISTANT_APPS:-}" ] && [ ! -w /Applications ]; then
    dir="$HOME/Applications"                             # нет прав на «Программы» — в личную папку программ
  fi
  mkdir -p "$dir"

  say "Узнаю последнюю версию…"
  local info tag url digest
  info=$(curl -fsSL -H "Accept: application/vnd.github+json" "https://api.github.com/repos/$REPO/releases/latest") \
    || die "нет связи с GitHub. Проверьте интернет и попробуйте ещё раз."
  # JSON разбирает JavaScript из macOS — без python и других программ, которых может не быть
  info=$(osascript -l JavaScript -e 'function run(a) {
      const r = JSON.parse(a[0]), x = (r.assets || []).find(x => x.name === a[1]);
      return x ? [r.tag_name, x.browser_download_url, x.digest || ""].join("\n") : "";
    }' "$info" "$file" </dev/null) || die "GitHub ответил непонятно. Попробуйте позже."
  [ -n "$info" ] || die "в последнем релизе нет файла $file."
  { read -r tag; read -r url; read -r digest; } <<<"$info"
  case "$url" in "https://github.com/$REPO/releases/download/"*) ;; *) die "неожиданная ссылка на скачивание: $url" ;; esac
  case "$digest" in sha256:*) ;; *) die "GitHub не сообщил контрольную сумму файла — установка остановлена." ;; esac

  tmp=$(mktemp -d)                                       # не local: ловушка EXIT срабатывает уже после выхода из main
  trap 'hdiutil detach -quiet "$tmp/mnt" >/dev/null 2>&1 || true; rm -rf "$tmp"' EXIT

  say "Скачиваю $NAME ${tag#v} ($arch)…"
  curl -fL --progress-bar -o "$tmp/$file" "$url" </dev/null || die "не удалось скачать $file."
  [ "$(shasum -a 256 "$tmp/$file" | cut -d' ' -f1)" = "${digest#sha256:}" ] \
    || die "контрольная сумма не совпала — файл повреждён при скачивании. Попробуйте ещё раз."

  mkdir "$tmp/mnt"
  hdiutil attach -nobrowse -readonly -quiet -mountpoint "$tmp/mnt" "$tmp/$file" </dev/null || die "не удалось открыть образ диска."
  [ -d "$tmp/mnt/$NAME.app" ] || die "в образе нет программы «$NAME»."

  local dest="$dir/$NAME.app"
  if [ -e "$dest" ]; then
    mkdir -p "$HOME/.Trash"
    mv "$dest" "$HOME/.Trash/$NAME $(date +%Y-%m-%d-%H%M%S).app" || die "не удалось убрать прежнюю версию из «$dir»."
    say "Прежняя версия — в Корзине."
  fi
  ditto "$tmp/mnt/$NAME.app" "$dest" || die "не удалось скопировать программу в «$dir»."
  xattr -dr com.apple.quarantine "$dest" 2>/dev/null || true
  codesign --verify --deep --strict "$dest" 2>/dev/null || die "подпись программы после копирования нарушена."

  say "Готово: $dest"
  say "Ваши профили и вакансии не тронуты."
  if [ -z "${VACANCY_ASSISTANT_NO_OPEN:-}" ]; then
    open "$dest"
  fi
}

main "$@"
