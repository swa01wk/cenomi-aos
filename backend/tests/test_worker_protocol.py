"""Worker protocol: leases, heartbeats and fencing (reference architecture 19.4).

An in-memory kernel stands in for the FastAPI worker API, enforcing the same rule the real one
will: only the current fencing token may act.
"""

from __future__ import annotations

import threading
import time
import unittest

from aos.worker.fake_model import FakeModel, ScriptedTurn
from aos.worker.protocol import Attempt, Fenced, Submission
from aos.worker.runner import AttemptFailed, Worker


class InMemoryKernel:
    def __init__(self, lease_seconds: float = 0.3):
        self.lease = lease_seconds
        self.lock = threading.Lock()
        self.queue = ["task_1"]
        self.token = {"task_1": 0}
        self.owner: dict[str, tuple[str, int, float]] = {}  # task -> (attempt, token, lease_expires)
        self.log: list[tuple[str, str]] = []
        self.submitted: list[tuple[str, Submission]] = []
        self.failed: list[tuple[str, str]] = []

    def _current(self, attempt: Attempt) -> None:
        owner = self.owner.get(attempt.task_id)
        if owner is None or owner[1] != attempt.fencing_token:
            self.log.append(("fenced", attempt.attempt_id))
            raise Fenced(attempt.attempt_id)

    def expire_leases(self) -> None:
        with self.lock:
            for task, (_, _, until) in list(self.owner.items()):
                if until < time.monotonic():
                    del self.owner[task]
                    self.queue.append(task)

    def claim(self, worker_id, lanes):
        self.expire_leases()
        with self.lock:
            if not self.queue:
                return None
            task = self.queue.pop(0)
            self.token[task] += 1
            n = self.token[task]
            aid = f"{task}#a{n}"
            self.owner[task] = (aid, n, time.monotonic() + self.lease)
            self.log.append(("claim", aid))
            return Attempt(aid, task, n, self.lease, {"objective": "test"})

    def heartbeat(self, attempt):
        with self.lock:
            self._current(attempt)
            self.owner[attempt.task_id] = (attempt.attempt_id, attempt.fencing_token, time.monotonic() + self.lease)

    def event(self, attempt, kind, data):
        with self.lock:
            self._current(attempt)
            self.log.append((kind, attempt.attempt_id))

    def submit(self, attempt, submission):
        with self.lock:
            self._current(attempt)
            self.submitted.append((attempt.attempt_id, submission))
            del self.owner[attempt.task_id]
            return {"status": "VERIFYING"}

    def fail(self, attempt, failure_class, message):
        with self.lock:
            self._current(attempt)
            self.failed.append((attempt.attempt_id, failure_class))
            del self.owner[attempt.task_id]


def ok_handler(attempt, ctx):
    ctx.emit("node", name="reason")
    return Submission(expected_task_version=1, input_artifact_digests={}, result_artifact_ids=["art_1"])


class WorkerProtocolTests(unittest.TestCase):
    def test_happy_path_submits_once(self) -> None:
        k = InMemoryKernel()
        self.assertEqual(Worker("w1", k, ok_handler).run_once(), "submitted")
        self.assertEqual([a for a, _ in k.submitted], ["task_1#a1"])
        self.assertEqual(Worker("w1", k, ok_handler).run_once(), "idle")

    def test_heartbeats_keep_a_long_attempt_alive(self) -> None:
        k = InMemoryKernel(lease_seconds=0.15)

        def slow(attempt, ctx):
            time.sleep(0.5)  # three leases long; heartbeats at lease/3 keep it
            k.expire_leases()
            return ok_handler(attempt, ctx)

        self.assertEqual(Worker("w1", k, slow).run_once(), "submitted")

    def test_stalled_worker_is_fenced_and_cannot_commit(self) -> None:
        # Worker A stalls past its lease, B takes over and finishes, A comes back: A's submit is rejected.
        k = InMemoryKernel(lease_seconds=0.1)
        a_may_resume = threading.Event()
        b_done = threading.Event()
        results = {}

        def stalls(attempt, ctx):
            a_may_resume.wait(2)
            return ok_handler(attempt, ctx)

        class NoHeartbeatWorker(Worker):
            def _heartbeat(self, attempt, stop, fenced):  # A's process is frozen: no heartbeats
                stop.wait(5)

        def run_a():
            results["a"] = NoHeartbeatWorker("A", k, stalls).run_once()

        ta = threading.Thread(target=run_a)
        ta.start()
        time.sleep(0.25)  # A's lease has expired
        results["b"] = Worker("B", k, ok_handler).run_once()
        b_done.set()
        a_may_resume.set()
        ta.join(3)
        self.assertEqual(results["b"], "submitted")
        self.assertEqual(results["a"], "fenced")
        self.assertEqual([a for a, _ in k.submitted], ["task_1#a2"], "only the current attempt committed")
        self.assertIn(("fenced", "task_1#a1"), k.log)

    def test_failures_are_classified(self) -> None:
        k = InMemoryKernel()

        def bad(attempt, ctx):
            raise AttemptFailed("validation", "output did not match the brief schema")

        self.assertEqual(Worker("w1", k, bad).run_once(), "failed:validation")
        self.assertEqual(k.failed, [("task_1#a1", "validation")])

    def test_unexpected_errors_are_unknown_not_retried_blindly(self) -> None:
        k = InMemoryKernel()

        def boom(attempt, ctx):
            raise RuntimeError("connector exploded")

        self.assertEqual(Worker("w1", k, boom).run_once(), "failed:unknown")


class FakeModelTests(unittest.TestCase):
    def test_scripted_turns_in_order(self) -> None:
        m = FakeModel([ScriptedTurn(tool_calls=[{"name": "search_suppliers"}]), ScriptedTurn(text="done")])
        self.assertEqual(m.invoke(["hi"]).tool_calls[0]["name"], "search_suppliers")
        self.assertEqual(m.invoke(["next"]).text, "done")
        with self.assertRaises(RuntimeError):
            m.invoke(["more"])


if __name__ == "__main__":
    unittest.main()
