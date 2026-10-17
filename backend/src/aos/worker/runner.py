"""The agent-worker loop: claim an attempt, keep its lease alive, run it, submit or fail.

The runtime that does the work (a LangGraph graph from M1, or a fake for tests) is injected as
a handler. The loop owns only the protocol: heartbeats at a third of the lease, stop on FENCED,
classify failures for the kernel's retry policy.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass

from .protocol import Attempt, Fenced, KernelClient, Submission

log = logging.getLogger("aos.worker")

Handler = Callable[[Attempt, "AttemptContext"], Submission]

FAILURE_CLASSES = ("transient", "permanent", "policy", "validation", "unknown", "exhausted")


class AttemptFailed(Exception):
    def __init__(self, failure_class: str, message: str):
        if failure_class not in FAILURE_CLASSES:
            raise ValueError(failure_class)
        super().__init__(message)
        self.failure_class = failure_class


@dataclass
class AttemptContext:
    """Handed to the runtime: the only way it can talk to the kernel, always fenced."""

    attempt: Attempt
    kernel: KernelClient
    fenced: threading.Event

    def emit(self, kind: str, **data) -> None:
        self.check()
        self.kernel.event(self.attempt, kind, data)

    def check(self) -> None:
        if self.fenced.is_set():
            raise Fenced(self.attempt.attempt_id)


class Worker:
    def __init__(self, worker_id: str, kernel: KernelClient, handler: Handler, lanes: tuple[str, ...] = ("background",)):
        self.worker_id = worker_id
        self.kernel = kernel
        self.handler = handler
        self.lanes = list(lanes)

    def _heartbeat(self, attempt: Attempt, stop: threading.Event, fenced: threading.Event) -> None:
        interval = max(attempt.lease_seconds / 3, 0.01)
        while not stop.wait(interval):
            try:
                self.kernel.heartbeat(attempt)
            except Fenced:
                fenced.set()
                return
            except Exception:  # noqa: BLE001 - a missed heartbeat is retried; the lease decides
                log.warning("heartbeat failed for %s", attempt.attempt_id, exc_info=True)

    def run_once(self) -> str:
        """Claim and run at most one attempt. Returns what happened, for logs and tests."""
        attempt = self.kernel.claim(self.worker_id, self.lanes)
        if attempt is None:
            return "idle"
        stop, fenced = threading.Event(), threading.Event()
        beat = threading.Thread(target=self._heartbeat, args=(attempt, stop, fenced), daemon=True)
        beat.start()
        ctx = AttemptContext(attempt, self.kernel, fenced)
        try:
            submission = self.handler(attempt, ctx)
            ctx.check()
            self.kernel.submit(attempt, submission)
            return "submitted"
        except Fenced:
            log.info("attempt %s fenced; stopping without effects", attempt.attempt_id)
            return "fenced"
        except AttemptFailed as exc:
            self._fail(attempt, exc.failure_class, str(exc))
            return f"failed:{exc.failure_class}"
        except Exception as exc:  # noqa: BLE001
            self._fail(attempt, "unknown", repr(exc))
            return "failed:unknown"
        finally:
            stop.set()
            beat.join(timeout=1)

    def _fail(self, attempt: Attempt, failure_class: str, message: str) -> None:
        try:
            self.kernel.fail(attempt, failure_class, message)
        except Fenced:
            pass
