"""Пробный запуск собранной программы (VacancyAssistant --self-check): при сборке установщика, до публикации.

Модуль или файл данных, не попавший в сборку, иначе ушёл бы пользователям — и программа сломалась бы у них.
Поэтому собранная программа сама поднимает свой сервер на свободном порту с временной папкой данных
и проверяет то, что увидит человек:
- окно: страница, стили и все скрипты, которые она подключает; /api/state;
- шаблоны промптов, образцы для мастера, «Где искать вакансии», сертификаты GigaChat, лицензия;
- «Помощь»: README и все документы и картинки, на которые он ссылается;
- все модули программы импортируются;
- https открывается (на Mac — корневые сертификаты на месте): последняя версия из репозитория релизов.
"""
import importlib
import json
import os
import pkgutil
import re
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote

PAGE_LINKS = re.compile(r'(?:src|href)="([^"#:]+\.(?:js|css|svg))"')
HELP_LINKS = re.compile(r'(?:href|src)="(docs/[^"#:]+)"')              # README: docs/<имя>.md
IMAGES = re.compile(r'src="(картинки/[^"#:]+)"')                       # документы: картинки/<имя>.svg


def _get(base, path, token=None):
    """(код, тело) ответа сервера программы."""
    request = urllib.request.Request(base + quote(path, safe="/%?=&"), headers={"X-Token": token} if token else {})
    try:
        with urllib.request.urlopen(request, timeout=30) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except OSError as e:                                # сервер не ответил
        return 0, str(e).encode("utf-8")


def check_files(problems):
    """Файлы данных из сборки на месте и читаются."""
    from . import cloud, links, settings
    from .textio import read_text
    templates = [v for k, v in vars(settings).items() if k.endswith("_TEMPLATE")]
    for f in templates + [settings.EXAMPLES / "резюме.md", settings.EXAMPLES / "критерии.txt",
                          settings.PROJECT_DIR / "LICENSE", settings.PROJECT_DIR / "README.md"]:
        try:
            if not read_text(f).strip():
                problems.append(f"пустой файл: {f.name}")
        except OSError:
            problems.append(f"нет файла: {f}")
    if not Path(cloud.CA_FILE).is_file():
        problems.append(f"нет сертификатов GigaChat: {cloud.CA_FILE}")
    try:
        links.load_builtin()
    except Exception as e:                              # noqa: BLE001
        problems.append(f"«Где искать вакансии»: {e}")
    return len(templates)


def check_modules(problems):
    """Все модули программы импортируются (в сборке может не оказаться модуля, который подключается не сразу)."""
    import vacancy_assistant
    names = [m.name for m in pkgutil.iter_modules(vacancy_assistant.__path__, "vacancy_assistant.")
             if not m.name.endswith(".__main__")]                # __main__ при импорте запускает программу
    if len(names) < 10:
        problems.append(f"модулей программы найдено только {len(names)}")
    for name in names:
        try:
            importlib.import_module(name)
        except Exception as e:                          # noqa: BLE001
            problems.append(f"модуль {name}: {e}")
    return len(names)


def check_server(problems):
    """Сервер программы с временной папкой данных: окно, скрипты, /api/state и «Помощь». → сколько запросов."""
    from . import app as A
    home = Path(os.environ["VACANCY_ASSISTANT_HOME"])
    app = A.App(home / "профили", check=lambda: {"ollama": False, "model_ok": False})
    server = A.make_server(app, port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base, count = f"http://127.0.0.1:{server.server_address[1]}", 0

    def get(path, token=None, kind="", need=b""):
        nonlocal count
        count += 1
        code, body = _get(base, path, token)
        if code != 200 or not body or (need and need not in body):
            problems.append(f"{kind or path}: ответ {code}, {len(body)} байт")
        return body.decode("utf-8", errors="replace")

    try:
        page = get("/", kind="страница окна", need=b"start()")
        assets = sorted(set(PAGE_LINKS.findall(page)))
        if not any(a.endswith(".js") for a in assets):
            problems.append("страница окна не подключает скриптов")
        for a in assets:
            get("/" + a.lstrip("/"))
        state = get("/api/state", token=app.token)
        try:
            if json.loads(state).get("version") is None:
                problems.append("/api/state: нет версии")
        except ValueError:
            problems.append("/api/state: ответ не JSON")
        get("/api/support", token=app.token)
        help_page = get("/help/", kind="«Помощь»")
        docs = sorted(set(HELP_LINKS.findall(help_page)))
        if not docs:
            problems.append("«Помощь» не ссылается ни на один документ")
        for d in docs:
            text = get("/help/" + d)
            for img in sorted(set(IMAGES.findall(text))):
                get("/help/docs/" + img)
    finally:
        server.shutdown()
        server.server_close()
    return count


def check_https(problems):
    from . import updates
    try:
        return updates.fetch_latest().get("version")
    except Exception as e:                              # noqa: BLE001
        problems.append(f"https: {e}")
        return None


def run(https=True, out=print):
    """Все проверки; out — куда писать отчёт. → 0, если всё в порядке, иначе 1."""
    from . import __version__
    problems = []
    home = Path(tempfile.mkdtemp(prefix="va-self-check-"))       # до всех проверок: данные человека не трогаем
    (home / "профили").mkdir()
    os.environ["VACANCY_ASSISTANT_HOME"] = str(home)               # и журнал, и настройки — во временной папке
    os.environ["VACANCY_ASSISTANT_CONFIG"] = str(home / "настройки")
    out(f"Помощник по вакансиям {__version__}: пробный запуск")
    out(f"модули: {check_modules(problems)}")
    out(f"шаблоны промптов: {check_files(problems)}")
    out(f"запросов к серверу окна: {check_server(problems)}")
    if https:
        out(f"https: последняя версия {check_https(problems)}")
    for p in problems:
        out("ОШИБКА: " + p)
    out("Пробный запуск: всё в порядке" if not problems else f"Пробный запуск: ошибок — {len(problems)}")
    return 1 if problems else 0
