"""Ожидание ответа модели, которое можно прервать (задача: GigaChat «завис»).

Запрос к модели блокирует поток задачи: пока он идёт, кнопка «Остановить» не срабатывала, а лог молчал —
казалось, что программа зависла. run() отправляет запрос в отдельном потоке, а поток задачи ждёт: раз в секунду
проверяет «Остановить», раз в LOG_EVERY секунд пишет в лог «жду ответа…», после limit секунд сдаётся с понятной
ошибкой. Брошенный запрос досчитается в фоне, его ответ никуда не пойдёт.

Задачу с окном связывает hook потока (tasks.Queues._run): hook(None) — проверить «Остановить» (бросает
tasks.Stopped), hook(текст) — строка в лог. Без hook (командная строка, тесты) — ждём так же, но молча.
"""
import threading
import time

LOG_EVERY = 30          # секунд между строками «жду ответа…»
STEP = 1.0              # как часто проверять «Остановить»

_current = threading.local()


def on_wait(hook):
    """Для этого потока: кого звать, пока ждём модель. None — никого."""
    _current.hook = hook


def run(call, who, limit, error):
    """call() в отдельном потоке; ждём не дольше limit секунд, иначе — error (AssistantError).
    who — чьего ответа ждём, для лога: «GigaChat», «локальной модели»."""
    hook = getattr(_current, "hook", None)
    box = {}

    def work():
        try:
            box["value"] = call()
        except BaseException as e:                       # noqa: BLE001 — передаём в поток задачи как есть
            box["error"] = e

    worker = threading.Thread(target=work, daemon=True)
    start = time.monotonic()
    worker.start()
    told = 0
    while True:
        worker.join(STEP)
        if not worker.is_alive():
            break
        waited = time.monotonic() - start
        if hook:
            hook(None)                                   # «Остановить» — бросит Stopped, запрос бросаем
            if waited >= told + LOG_EVERY:
                told += LOG_EVERY
                hook(f"      жду ответа {who}… {told} с")
        if waited >= limit:
            raise error
    if "error" in box:
        raise box["error"]
    return box["value"]
