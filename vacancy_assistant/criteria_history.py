"""История версий: критерии (с оценкой эффективности) и образец письма.

Папка профиля «история критериев/»: тексты версий (<номер>.txt) и список с описанием (версии.json).
Версия попадает сюда, когда критерии правят в мастере (прежний текст), когда их проверяет
автонастройка (каждая версия — с показателями на ваших оценках) и когда применяют лучшую версию.
Одинаковые тексты не дублируются: у версии копятся замеры, показываем последний.
Так же хранятся версии образца письма — в «история образца письма/», без замеров (which="letter");
у других шаблонов письма (#53) — своя папка: which="letter:2" → «история образца письма 2/».
"""
import re
from datetime import datetime

from .textio import read_json, read_text, write_json, write_text

FOLDER = "история критериев"
FOLDERS = {"criteria": FOLDER, "letter": "история образца письма"}


def folder_name(which):
    if which.startswith("letter:"):
        return f"{FOLDERS['letter']} {int(which[7:])}"
    return FOLDERS[which]


def _current(profile, which):
    from . import letter_templates
    f = profile.criteria_file if which == "criteria" else letter_templates.file(profile, int(which[7:]) if ":" in which else 1)
    return read_text(f) if f.exists() else ""


def _norm(text):
    return re.sub(r"\s+", " ", (text or "").strip())


def _index(profile, which="criteria"):
    f = profile.dir / folder_name(which) / "версии.json"
    return read_json(f, [])


def _save_index(profile, items, which="criteria"):
    write_json(profile.dir / folder_name(which) / "версии.json", items)


def record(profile, text, source, metrics=None, when=None, kind=None, which="criteria"):
    """Сохраняет версию критериев (если такой ещё нет) и, если есть, её замер. Возвращает номер версии.
    kind — откуда текст: «manual» (правили вручную), «questionnaire» (из опросника), «tune» (автонастройка)."""
    if not (text or "").strip():
        return None
    folder = profile.dir / folder_name(which)
    folder.mkdir(exist_ok=True)
    items = _index(profile, which)
    when = when or datetime.now().strftime("%Y-%m-%d %H:%M")
    same = next((i for i in items if _norm(read_text(folder / i["file"])) == _norm(text)), None)
    if same is None:
        num = max((i["id"] for i in items), default=0) + 1
        same = {"id": num, "file": f"{num:03d}.txt", "date": when, "source": source, "measures": [],
                "kind": kind or ("tune" if metrics else "other")}
        write_text(folder / same["file"], text.strip() + "\n")
        items.append(same)
    measure = {"date": when, "source": source, **metrics} if metrics else None
    if measure and measure not in same["measures"]:          # тот же замер повторно не добавляем
        same["measures"].append(measure)
    _save_index(profile, items, which)
    return same["id"]


def import_tune(profile, tune_dir):
    """Переносит в историю версии последней автонастройки (настройка/критерии vK.txt) с их показателями."""
    summary_file = tune_dir / "итог.json"
    if not summary_file.exists():
        return
    summary = read_json(summary_file)
    for v in summary.get("versions", []):
        f = tune_dir / f"критерии {v['version']}.txt"
        if f.exists():
            m = v.get("metrics")
            metrics = {"всего": m["всего"], "совпало": m["решение совпало"], "пропущено": m["пропущено подходящих"],
                       "лишних": m["лишних да"]} if m else None
            record(profile, read_text(f), f"автонастройка {summary['date']}, {v['version']}: {v['what']}",
                   metrics, when=summary["date"], kind="tune")
    for f in sorted(tune_dir.glob("критерии до применения *.txt")):
        record(profile, read_text(f), "до применения автонастройки", when=summary["date"])


def delete(profile, version_id, which="criteria"):
    """Удаляет ручную версию, которую ещё не проверяли на калибровке (и не текущую)."""
    from .errors import AssistantError
    v = next((v for v in versions(profile, which) if v["id"] == version_id), None)
    if v is None:
        raise AssistantError("Нет такой версии критериев.")
    if v["kind"] != "manual" or v["measures"] or v["current"]:
        raise AssistantError("Удалять можно только ручные версии без калибровочных прогонов, и не текущую.")
    items = _index(profile, which)
    entry = next(i for i in items if i["id"] == version_id)
    (profile.dir / folder_name(which) / entry["file"]).unlink(missing_ok=True)
    _save_index(profile, [i for i in items if i["id"] != version_id], which)


def versions(profile, which="criteria"):
    """Все версии, новые сверху: номер, дата, откуда, текст, последний замер, текущая ли."""
    folder = profile.dir / folder_name(which)
    current = _norm(_current(profile, which))
    result = []
    for i in _index(profile, which):
        text = read_text(folder / i["file"])
        result.append({"id": i["id"], "date": i["date"], "source": i["source"], "text": text.strip(),
                       "kind": i.get("kind", "other"),
                       "measure": i["measures"][-1] if i["measures"] else None,
                       "measures": len(i["measures"]), "current": _norm(text) == current})
    return sorted(result, key=lambda v: (v["date"], v["id"]), reverse=True)
