"""Async worker loop: claim, heartbeat, run runtime, submit or fail."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from .errors import (
    AttemptWaitingForInput,
    AuthFailed,
    BudgetExhausted,
    Fenced,
    KernelProblemError,
    KernelTransportError,
    TransientKernelError,
    ValidationFailed,
)
from .protocol import AttemptContext, AttemptFailed
from .runtime import AgentRuntime
from .types import WorkerAttempt
from .validate import agent_result_valid

if TYPE_CHECKING:
    from .http_client import HttpKernelClient

log = logging.getLogger("aos.worker")


class Worker:
    def __init__(
        self,
        worker_id: str,
        kernel: HttpKernelClient,
        runtime: AgentRuntime,
        lanes: tuple[str, ...] = ("assist", "task"),
        *,
        heartbeat_enabled: bool = True,
        ignore_local_lease_deadline: bool = False,
        submit_shutdown_timeout_s: float = 30.0,
        poll_min_s: float = 1.0,
        poll_max_s: float = 5.0,
    ):
        self.worker_id = worker_id
        self.kernel = kernel
        self.runtime = runtime
        self.lanes = list(lanes)
        self.heartbeat_enabled = heartbeat_enabled
        self.ignore_local_lease_deadline = ignore_local_lease_deadline
        self.submit_shutdown_timeout_s = submit_shutdown_timeout_s
        self.poll_min_s = poll_min_s
        self.poll_max_s = poll_max_s
        self._shutdown = asyncio.Event()
        self._runtime_task: asyncio.Task | None = None

    def request_shutdown(self) -> None:
        self._shutdown.set()
        task = self._runtime_task
        if task is not None and not task.done():
            task.cancel()

    async def _heartbeat_loop(
        self,
        attempt: WorkerAttempt,
        ctx: AttemptContext,
        stop: asyncio.Event,
    ) -> None:
        interval = float(attempt["lease_seconds"]) / 3.0
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval)
                return
            except asyncio.TimeoutError:
                pass
            if stop.is_set():
                return
            try:
                ctx.check()
                sent_at = time.monotonic()
                hb = await self.kernel.heartbeat(attempt)
                ctx.extend_lease(heartbeat_sent_at=sent_at)
                if hb.get("cancel_requested"):
                    ctx.fenced.set()
                    return
            except AuthFailed:
                ctx.fenced.set()
                return
            except Fenced:
                ctx.fenced.set()
                return
            except Exception:
                log.warning("heartbeat failed for %s", attempt["attempt_id"], exc_info=True)

    async def run_once(self) -> str:
        try:
            attempt = await self.kernel.claim(self.worker_id, self.lanes)
        except Fenced:
            return "fenced"
        if attempt is None:
            return "idle"

        fenced = asyncio.Event()
        ctx = AttemptContext(
            attempt,
            self.kernel,
            fenced,
            ignore_local_lease_deadline=self.ignore_local_lease_deadline,
        )
        stop = asyncio.Event()
        beat_task: asyncio.Task | None = None
        if self.heartbeat_enabled:
            beat_task = asyncio.create_task(self._heartbeat_loop(attempt, ctx, stop))

        runtime_task = asyncio.create_task(self._run_attempt(attempt, ctx))
        self._runtime_task = runtime_task
        try:
            while not runtime_task.done():
                if self._shutdown.is_set():
                    runtime_task.cancel()
                elif fenced.is_set():
                    runtime_task.cancel()
                elif ctx.lease_expired():
                    runtime_task.cancel()
                await asyncio.sleep(0.02)

            try:
                outcome = await runtime_task
            except asyncio.CancelledError:
                if self._shutdown.is_set():
                    return "shutdown"
                return "fenced"
            except Fenced:
                return "fenced"
            except AttemptWaitingForInput:
                return "waiting"
            except AttemptFailed as exc:
                await self._fail(attempt, exc.failure_class, str(exc))
                return f"failed:{exc.failure_class}"
            except BudgetExhausted as exc:
                try:
                    await self.kernel.fail_attempt(
                        attempt, "budget_exhausted", exc.detail or exc.title
                    )
                except Fenced:
                    return "fenced"
                return "failed:budget_exhausted"
            except Exception as exc:
                await self._fail(attempt, "internal", repr(exc))
                return "failed:internal"

            if self._shutdown.is_set():
                return "shutdown"
            if fenced.is_set():
                return "fenced"
            try:
                ctx.check()
            except Fenced:
                return "fenced"

            if not agent_result_valid(dict(outcome)):
                from .validate import agent_result_errors

                msg = "; ".join(agent_result_errors(dict(outcome)))[:2000]
                await self._fail(attempt, "invalid_output", msg or "agent result failed schema validation")
                return "failed:invalid_output"

            try:
                if self._shutdown.is_set():
                    await asyncio.wait_for(
                        asyncio.shield(self.kernel.submit_result(attempt, outcome)),
                        timeout=self.submit_shutdown_timeout_s,
                    )
                else:
                    await self.kernel.submit_result(attempt, outcome)
            except asyncio.TimeoutError:
                log.warning("submit timed out during shutdown for %s", attempt["attempt_id"])
                return "shutdown"
            except Fenced:
                return "fenced"
            except ValidationFailed as exc:
                msg = (exc.detail or exc.title or "kernel rejected submit")[:2000]
                await self._fail(attempt, "invalid_output", msg)
                return "failed:invalid_output"
            except KernelProblemError as exc:
                log.warning(
                    "kernel rejected submit for %s: %s",
                    attempt["attempt_id"],
                    exc,
                )
                return "submit_rejected"
            return "submitted"
        finally:
            self._runtime_task = None
            stop.set()
            if beat_task is not None:
                beat_task.cancel()
                try:
                    await beat_task
                except asyncio.CancelledError:
                    pass

    async def _run_attempt(self, attempt: WorkerAttempt, ctx: AttemptContext) -> dict:
        if attempt.get("resume"):
            return await self.runtime.resume(attempt, ctx)
        return await self.runtime.start(attempt, ctx)

    async def _fail(self, attempt: WorkerAttempt, failure_class: str, message: str) -> None:
        try:
            await self.kernel.fail_attempt(attempt, failure_class, message)
        except Fenced:
            pass

    async def run_forever(self) -> None:
        poll = self.poll_min_s
        while not self._shutdown.is_set():
            try:
                result = await self.run_once()
            except AuthFailed:
                log.error("worker token rejected; exiting")
                raise SystemExit(1) from None
            except (KernelTransportError, TransientKernelError, KernelProblemError) as exc:
                log.warning("kernel claim failed: %s", exc)
                try:
                    await asyncio.wait_for(self._shutdown.wait(), timeout=poll)
                    break
                except asyncio.TimeoutError:
                    poll = min(poll * 1.5, self.poll_max_s)
                continue
            if result in ("shutdown",):
                break
            if result == "idle":
                try:
                    await asyncio.wait_for(self._shutdown.wait(), timeout=poll)
                    break
                except asyncio.TimeoutError:
                    poll = min(poll * 1.5, self.poll_max_s)
                continue
            if self._shutdown.is_set():
                break
            poll = self.poll_min_s
