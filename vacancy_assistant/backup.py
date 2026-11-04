"""Резервные копии профилей: архив .zip папки профиля в «копии/» рядом с «профили/».

Ключ GigaChat и пароль домашней сети лежат вне папок профилей и в копию не входят. Автокопия — раз в неделю
при запуске программы, хранятся последние четыре; старые и заменённые при восстановлении — в Корзину, не удаляются.
"""
import json
import re
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

from . import __version__
from .errors import AssistantError
from .profile import CONFIG_FILE, profile_names
from .textio import read_json, write_json

MANIFEST = "копия.json"
AUTO = " авто"                 # в имени автокопии: «maria 2026-10-26 09-00 авто.zip»
KEEP_AUTO = 4
AUTO_EVERY = timedelta(days=7)
SKIP = {".DS_Store", "__pycache__", "Thumbs.db"}
MAX_SIZE = 2 * 1024 ** 3       # распакованный архив больше 2 ГБ — не копия профиля
NAME = r"[\w-]{1,40}"          # имя папки профиля, как при переименовании


def copies_dir(profiles_root):
    return Path(profiles_root).parent / "копии"


def make(profile, auto=False, now=None):
    """Архив папки профиля → путь к нему."""
    now = now or datetime.now()
    folder = copies_dir(profile.dir.parent)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = now.strftime("%Y-%m-%d %H-%M")
    path = folder / f"{profile.name} {stamp}{AUTO if auto else ''}.zip"
    if path.exists():
        path = path.with_name(f"{profile.name} {now.strftime('%Y-%m-%d %H-%M-%S')}{AUTO if auto else ''}.zip")
    manifest = {"программа": "Помощник по вакансиям", "версия": __version__, "профиль": profile.name,
                "имя": profile.display_name, "создана": now.isoformat(timespec="seconds"), "авто": auto}
    tmp = path.with_suffix(".zip.tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=2))
        for f in sorted(profile.dir.rglob("*")):
            rel = f.relative_to(profile.dir)
            if f.is_file() and not SKIP.intersection(rel.parts):
                z.write(f, f"{profile.name}/{rel.as_posix()}")
    tmp.replace(path)                                  # недописанный архив не попадёт в список копий
    return path


def manifest_of(z):
    try:
        return json.loads(z.read(MANIFEST).decode("utf-8"))
    except (KeyError, ValueError):
        raise AssistantError("Это не резервная копия профиля: в архиве нет описания копии.") from None


def listing(profiles_root):
    """Копии всех профилей, новые сверху: файл, профиль, имя, когда создана, авто, размер."""
    out = []
    for f in copies_dir(profiles_root).glob("*.zip"):
        try:
            with zipfile.ZipFile(f) as z:
                m = manifest_of(z)
        except (zipfile.BadZipFile, AssistantError, OSError):
            continue
        out.append({"file": f.name, "profile": m.get("профиль", ""), "name": m.get("имя", ""),
                    "created": m.get("создана", ""), "auto": bool(m.get("авто")), "size": f.stat().st_size})
    return sorted(out, key=lambda c: c["created"], reverse=True)


def copy_path(profiles_root, file):
    """Файл копии по имени из списка — только из папки копий, никаких «../»."""
    path = copies_dir(profiles_root) / Path(file or "").name
    if path.suffix != ".zip" or not path.is_file():
        raise AssistantError("Нет такой копии.")
    return path


def auto(profiles_root, now=None, trash=None, log=print):
    """Автокопия профилей, у которых её не было неделю; лишние автокопии (старше четырёх последних) — в Корзину."""
    now = now or datetime.now()
    from .profile import Profile
    copies = listing(profiles_root)
    for name in profile_names(profiles_root):
        mine = [c for c in copies if c["profile"] == name and c["auto"]]
        if not mine or datetime.fromisoformat(mine[0]["created"]) <= now - AUTO_EVERY:
            path = make(Profile(name, Path(profiles_root)), auto=True, now=now)
            log(f"Резервная копия профиля {name}: {path}")
            mine.insert(0, {"file": path.name})
        for c in mine[KEEP_AUTO:]:
            (trash or move_to_trash)(copies_dir(profiles_root) / c["file"])


def free_name(profiles_root, base):
    base = re.sub(r"[^\w-]", "", base)[:28] or "профиль"
    name, n = f"{base}-восстановлен", 2
    while (Path(profiles_root) / name).exists():
        name, n = f"{base}-восстановлен-{n}", n + 1
    return name


def opened(archive):
    """Архив копии → (ZipFile, описание копии, имя профиля в копии, файлы профиля). Проверяет, что это копия
    профиля, не из более новой версии программы и без файлов вне папки профиля."""
    try:
        z = zipfile.ZipFile(archive)
    except zipfile.BadZipFile:
        raise AssistantError("Это не архив .zip — выберите файл резервной копии.") from None
    try:
        m = manifest_of(z)
        if version(m.get("версия", "0")) > version(__version__):
            raise AssistantError(f"Копия сделана в более новой версии программы ({m.get('версия')}). "
                                 "Обновите программу и повторите.")
        old = m.get("профиль", "")
        members = [i for i in z.infolist() if i.filename != MANIFEST]
        for i in members:
            parts = Path(i.filename).parts
            if i.filename.startswith(("/", "\\")) or ".." in parts or not parts or parts[0] != old or ":" in i.filename:
                raise AssistantError("Архив повреждён: в нём файлы вне папки профиля.")
        if f"{old}/{CONFIG_FILE}" not in {i.filename for i in members}:
            raise AssistantError("В архиве нет профиль.json — это не копия профиля.")
        if sum(i.file_size for i in members) > MAX_SIZE:
            raise AssistantError("Архив слишком большой для копии профиля.")
    except Exception:
        z.close()
        raise
    return z, m, old, members


def inspect(profiles_root, archive):
    """Что в архиве — перед переносом профиля: имя, когда сделана копия, модель и свободное имя папки."""
    z, m, old, _ = opened(archive)
    with z:
        config = json.loads(z.read(f"{old}/{CONFIG_FILE}").decode("utf-8"))
    return {"profile": old, "name": config.get("имя", old), "created": m.get("создана", ""),
            "version": m.get("версия", ""), "cloud": bool((config.get("модель") or {}).get("облако")),
            "suggested": default_name(profiles_root, old)}


def default_name(profiles_root, old):
    """Имя папки при переносе: прежнее, если свободно, иначе «<имя>-восстановлен»."""
    return old if re.fullmatch(NAME, old) and not (Path(profiles_root) / old).exists() else free_name(profiles_root, old)


def restore(profiles_root, archive, into=None, trash=None, name=None):
    """Восстановить профиль из архива (путь или открытый файл). into=None — новым профилем: с именем name,
    а без него — прежним, если свободно, иначе «<имя>-восстановлен». into=Profile — вместо него: текущий
    сначала сохраняется в копию, а его папка уходит в Корзину. Возвращает имя восстановленного профиля."""
    root = Path(profiles_root)
    z, _, old, members = opened(archive)
    with z:
        if into:
            name = into.name
        elif name:
            name = name.strip()
            if not re.fullmatch(NAME, name):
                raise AssistantError("Имя профиля — буквы, цифры, «-» или «_», без пробелов (например, maria).")
            if (root / name).exists():
                raise AssistantError(f"Профиль «{name}» уже есть — выберите другое имя.")
        else:
            name = default_name(root, old)
        tmp = root / f".восстановление {name}"
        if tmp.exists():
            (trash or move_to_trash)(tmp)                  # остаток прерванного восстановления
        for i in members:
            if not i.is_dir():
                target = tmp / Path(i.filename).relative_to(old)
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(i) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
    config_file = tmp / CONFIG_FILE
    config = read_json(config_file)
    vault = config.get("путь_в_obsidian", "")
    if name != old and (vault == old or vault.endswith("/" + old)):    # ссылки Meta Bind — с путём профиля
        config["путь_в_obsidian"] = vault[: len(vault) - len(old)] + name
        write_json(config_file, config)
    if into:
        make(into)
        (trash or move_to_trash)(into.dir)
    tmp.rename(root / name)
    return name


def version(v):
    return tuple(int(x) for x in re.findall(r"\d+", str(v))[:3])


def move_to_trash(path):
    """В Корзину системы, не удаляя: из неё можно достать."""
    path = Path(path)
    if sys.platform == "win32":
        kind = "DeleteDirectory" if path.is_dir() else "DeleteFile"
        subprocess.run(["powershell", "-NoProfile", "-Command",
                        "Add-Type -AssemblyName Microsoft.VisualBasic; [Microsoft.VisualBasic.FileIO.FileSystem]::"
                        f"{kind}($args[0], 'OnlyErrorDialogs', 'SendToRecycleBin')", str(path)], check=True)
        return
    bin_ = Path.home() / (".Trash" if sys.platform == "darwin" else ".local/share/Trash/files")
    bin_.mkdir(parents=True, exist_ok=True)
    target, n = bin_ / path.name, 2
    while target.exists():
        target, n = bin_ / f"{path.stem} {n}{path.suffix}", n + 1
    shutil.move(str(path), str(target))


def reveal(path):
    """Показать файл или папку в Finder / Проводнике."""
    path = Path(path)
    if sys.platform == "darwin":
        subprocess.run(["open", "-R", str(path)] if path.is_file() else ["open", str(path)])
    elif sys.platform == "win32":
        subprocess.run(["explorer", f"/select,{path}"] if path.is_file() else ["explorer", str(path)])
    else:
        subprocess.run(["xdg-open", str(path if path.is_dir() else path.parent)])
