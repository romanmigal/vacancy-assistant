"""Очереди задач к моделям: локальная (Ollama) и облачная (GigaChat). У каждой — свой поток-обработчик:
задачи на разных моделях идут параллельно, на одной — по очереди (Ollama и так отвечает на один запрос
за раз, у GigaChat один ключ на компьютер).

Виды задач:
- пачка (batch) — поиск и разбор, автонастройка, переоценка: у профиля одна за раз;
- одиночная (single) — по кнопке для одной вакансии: письмо, «Разобрать заново», добавить по ссылке. Не ждёт
  конца пачки — пачка пропускает её вперёд между вакансиями;
- служебная (service) — скачивание модели в мастере, без профиля.

Задачу профиля целиком (название, лог) видит только этот профиль, другим — «задача другого профиля».
"""
import re
import threading
import time
import traceback

from . import cloud, waiting
from .errors import AssistantError

QUEUES = {"local": "локальная модель", "cloud": "GigaChat"}
KEEP_DONE = 3600            # законченные задачи показываются час…
KEEP_MAX = 30               # …но не больше стольких
# Строки лога, на которых пачку можно прервать одиночной задачей: начало вакансии «[3/50] …» или этап «▶ …»
BOUNDARY = re.compile(r"^(▶ |\s*\[\d+/\d+\] )")
ACTIVE = ("queued", "running")


class Stopped(AssistantError):
    """Задачу остановили кнопкой «Остановить»."""


class Task:
    def __init__(self, tid, queue, kind, title, work, profile=None, action="", n=None):
        self.id, self.queue, self.kind, self.title, self.work = tid, queue, kind, title, work
        self.profile, self.owner = profile, (profile.name if profile else "")
        self.action, self.n = action, n
        self.status, self.phase, self.log, self.error = "queued", "", [], ""
        self.created, self.finished = time.time(), None
        self.stop_requested = False
        self.inside = None              # пачка пропустила вперёд одиночную — какую (её название)

    @property
    def active(self):
        return self.status in ACTIVE


class Queues:
    def __init__(self):
        self.lock = threading.Condition()
        self.tasks = []
        self.next_id = 1
        self.workers = {}

    # --- постановка, остановка, состояние

    def add(self, kind, title, work, profile=None, action="", n=None, queue=None):
        """Поставить задачу в очередь модели профиля. Возвращает задачу."""
        queue = queue or ("cloud" if cloud.active(profile) else "local")
        with self.lock:
            mine = [t for t in self.tasks if t.active and profile and t.owner == profile.name]
            if kind == "batch" and mine:
                raise AssistantError("У профиля ещё идут задачи — запустите это, когда они закончатся "
                                     "(или остановите их на панели задач).")
            if n is not None and any(t.action == action and t.n == n for t in mine):
                raise AssistantError("Это уже в очереди.")
            task = Task(self.next_id, queue, kind, title, work, profile, action, n)
            self.next_id += 1
            self.tasks.append(task)
            self._prune()
            if queue not in self.workers:
                self.workers[queue] = threading.Thread(target=self._worker, args=(queue,), daemon=True)
                self.workers[queue].start()
            self.lock.notify_all()
            return task

    def busy(self, owner):
        """Есть ли у профиля задачи в очереди или в работе."""
        with self.lock:
            return any(t.active and t.owner == owner for t in self.tasks)

    def running(self):
        with self.lock:
            return any(t.active for t in self.tasks)

    def get(self, tid):
        with self.lock:
            return next((t for t in self.tasks if t.id == tid), None)

    def stop(self, tid, viewer):
        """Остановить свою задачу (идущая закончится после текущего шага) или убрать её из очереди."""
        with self.lock:
            t = next((t for t in self.tasks if t.id == tid), None)
            if not t or (t.owner and t.owner != viewer):
                raise AssistantError("Такой задачи нет — возможно, она уже закончилась.")
            if t.status == "queued":
                t.status, t.finished = "removed", time.time()
            elif t.status == "running":
                t.stop_requested = True
                t.phase = "останавливаю после текущего шага"

    def stop_all(self):
        with self.lock:
            for t in self.tasks:
                if t.status == "queued":
                    t.status, t.finished = "removed", time.time()
                elif t.status == "running":
                    t.stop_requested = True

    def position(self, task):
        """Место в очереди: 1 — следующая. Одиночные идут раньше пачек (пачка пропускает их вперёд)."""
        with self.lock:
            if task.status != "queued":
                return 0
            waiting = [t for t in self.tasks if t.queue == task.queue and t.status == "queued"]
            singles = [t for t in waiting if t.kind == "single"]
            order = singles + [t for t in waiting if t.kind != "single"] if self._batch_running(task.queue) else waiting
            return order.index(task) + 1

    def view(self, task, viewer):
        """Задача для окна: своя — целиком, чужая — только что занято и чем (очередь, место)."""
        base = {"id": task.id, "queue": task.queue, "queue_name": QUEUES[task.queue], "status": task.status,
                "kind": task.kind, "position": self.position(task)}
        if task.owner and task.owner != viewer:
            return {**base, "foreign": True, "title": "Задача другого профиля", "log": [], "count": 0,
                    "phase": "", "error": "", "action": "", "n": None}
        with self.lock:
            return {**base, "foreign": False, "title": task.title, "phase": task.phase, "error": task.error,
                    "action": task.action, "n": task.n, "inside": task.inside,
                    "log": list(task.log[-300:]), "count": len(task.log),
                    "created": task.created, "finished": task.finished}

    def snapshot(self, viewer):
        """Задачи для окна профиля viewer: свои — в работе, в очереди и законченные за час;
        чужие — только в работе и в очереди (видно, почему ждём)."""
        with self.lock:
            self._prune()
            shown = [t for t in self.tasks if t.active or (t.owner == viewer or not t.owner)]
        return [self.view(t, viewer) for t in shown]

    # --- обработчики очередей

    def _batch_running(self, queue):
        return any(t.queue == queue and t.status == "running" and t.kind != "single" for t in self.tasks)

    def _prune(self):
        now = time.time()
        done = [t for t in self.tasks if not t.active]
        old = {id(t) for t in done if now - (t.finished or now) > KEEP_DONE} | {id(t) for t in done[:-KEEP_MAX]}
        self.tasks = [t for t in self.tasks if id(t) not in old]

    def _take(self, queue, singles_only=False):
        """Следующая задача очереди (под замком); singles_only — только одиночная, для пачки."""
        task = next((t for t in self.tasks if t.queue == queue and t.status == "queued"
                     and (not singles_only or t.kind == "single")), None)
        if task:
            task.status = "running"
        return task

    def _worker(self, queue):
        while True:
            with self.lock:
                task = self._take(queue)
                while not task:
                    self.lock.wait()
                    task = self._take(queue)
            self._run(task)

    def _run(self, task):
        before = cloud.current_profile()
        cloud.use(task.profile)                          # задача профиля — модель этого профиля
        waiting.on_wait(lambda message: self._log(task, message) if message else self._check_stop(task))
        try:
            task.work(lambda message="": self._log(task, message))
            status = "done"
        except Stopped as e:
            status = "stopped"
            with self.lock:
                task.log.append(str(e))
        except AssistantError as e:
            status, task.error = "error", str(e)
        except Exception as e:                           # noqa: BLE001 — показать в окне, а не уронить сервер
            status, task.error = "error", f"Ошибка: {e}"
            traceback.print_exc()
        finally:
            cloud.use(before)
            waiting.on_wait(None)
        with self.lock:
            task.status, task.finished = status, time.time()
            self.lock.notify_all()

    def _check_stop(self, task):
        if task.stop_requested:
            raise Stopped("Остановлено. Уже сделанное сохранено — продолжить можно той же кнопкой.")

    def _log(self, task, message):
        self._check_stop(task)
        lines = str(message).strip("\n").split("\n") if message else [""]
        with self.lock:
            task.log.extend(lines)
            for line in lines:
                if line.startswith("▶ "):                # этап: «▶ Ищу на hh.ru…» — его показывает окно
                    task.phase = line[2:]
        if task.kind == "batch" and any(BOUNDARY.match(line) for line in lines):
            self._let_singles_through(task)

    def _let_singles_through(self, batch):
        """Между вакансиями пачки — одиночные задачи той же очереди: письмо не ждёт 50 минут разбора."""
        while True:
            with self.lock:
                single = self._take(batch.queue, singles_only=True)
                if not single:
                    batch.inside = None
                    return
                batch.inside = single.title if single.owner == batch.owner else "задача другого профиля"
            self._run(single)
