"""Очереди задач к моделям: параллельно на разных моделях, по очереди на одной, одиночные — между вакансиями пачки."""
import threading
import time
import unittest
from types import SimpleNamespace

import helpers  # noqa: F401 — путь к проекту

from vacancy_assistant.errors import AssistantError
from vacancy_assistant.tasks import Queues

ANNA, BORIS = SimpleNamespace(name="anna"), SimpleNamespace(name="boris")


def wait_idle(q, timeout=5):
    end = time.time() + timeout
    while q.running():
        if time.time() > end:
            raise AssertionError("очередь не опустела")
        time.sleep(0.01)


class Queue(unittest.TestCase):
    def test_different_models_run_in_parallel(self):
        q, met = Queues(), threading.Event()
        q.add("batch", "А", lambda log: met.wait(2), ANNA, queue="local")
        q.add("batch", "Б", lambda log: met.set(), BORIS, queue="cloud")
        wait_idle(q)
        self.assertTrue(met.is_set())
        self.assertEqual({t.status for t in q.tasks}, {"done"})

    def test_same_model_one_by_one(self):
        q, order, inside, most = Queues(), [], [], []

        def work(name):
            def run(log):
                inside.append(name)
                most.append(len(inside))                      # сколько задач работает одновременно
                time.sleep(0.05)
                order.append(name)
                inside.remove(name)
            return run
        q.add("batch", "А", work("А"), ANNA, queue="local")
        q.add("batch", "Б", work("Б"), BORIS, queue="local")
        wait_idle(q)
        self.assertEqual((order, max(most)), (["А", "Б"], 1))

    def test_batch_rules(self):
        q, go = Queues(), threading.Event()
        q.add("batch", "Пачка", lambda log: go.wait(2), ANNA, queue="local")
        with self.assertRaises(AssistantError):
            q.add("batch", "Ещё пачка", lambda log: None, ANNA, queue="local")   # у профиля уже есть задача
        single = q.add("single", "Письмо", lambda log: None, ANNA, "letter", 5, queue="local")
        with self.assertRaises(AssistantError):
            q.add("single", "Письмо", lambda log: None, ANNA, "letter", 5, queue="local")   # то же — уже в очереди
        q.add("batch", "Пачка Бориса", lambda log: None, BORIS, queue="local")   # другой профиль — можно
        self.assertEqual(q.position(single), 1)
        self.assertTrue(q.busy("anna"))
        go.set()
        wait_idle(q)
        self.assertFalse(q.busy("anna"))

    def test_single_runs_between_batch_items(self):
        q, order, started, go = Queues(), [], threading.Event(), threading.Event()

        def batch(log):
            log("[1/2] Оцениваю: первая")
            started.set()
            go.wait(2)
            order.append("пачка: первая")
            log("[2/2] Оцениваю: вторая")              # граница вакансий — здесь пропускает одиночные
            order.append("пачка: вторая")
        q.add("batch", "Разбор", batch, ANNA, queue="local")
        started.wait(2)
        q.add("single", "Письмо", lambda log: order.append("письмо"), BORIS, "letter", 1, queue="local")
        go.set()
        wait_idle(q)
        self.assertEqual(order, ["пачка: первая", "письмо", "пачка: вторая"])

    def test_stop_and_remove(self):
        q, started = Queues(), threading.Event()

        def endless(log):
            started.set()
            while True:
                log("шаг")
                time.sleep(0.01)
        running = q.add("batch", "Долгая", endless, ANNA, queue="local")
        waiting = q.add("single", "Письмо", lambda log: self.fail("убранная из очереди не должна идти"),
                        BORIS, "letter", 1, queue="local")
        started.wait(2)
        with self.assertRaises(AssistantError):
            q.stop(running.id, "boris")                 # чужую — нельзя
        q.stop(waiting.id, "boris")
        q.stop(running.id, "anna")
        wait_idle(q)
        self.assertEqual((running.status, waiting.status), ("stopped", "removed"))

    def test_foreign_tasks_hidden(self):
        q, go = Queues(), threading.Event()
        q.add("batch", "Разбор · Анна", lambda log: (log("секрет"), go.wait(2)), ANNA, queue="local")
        time.sleep(0.05)
        mine, = q.snapshot("anna")
        theirs, = q.snapshot("boris")
        self.assertEqual((mine["title"], mine["log"]), ("Разбор · Анна", ["секрет"]))
        self.assertEqual((theirs["title"], theirs["log"], theirs["foreign"]), ("Задача другого профиля", [], True))
        go.set()
        wait_idle(q)
        self.assertEqual(q.snapshot("boris"), [])                # законченные чужие не показываются
        self.assertEqual(len(q.snapshot("anna")), 1)


if __name__ == "__main__":
    unittest.main()
