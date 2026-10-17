"""Async worker loop: claim, heartbeat, run runtime, submit or fail."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from .errors import AuthFailed, BudgetExhausted, Fenced, KernelTransportError
from .protocol import AttemptContext, AttemptFailed
from .runtime import AgentRuntime
from .types import WorkerAttempt

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
        submit_shutdown_timeout_s: float = 30.0,
    ):
        self.worker_id = worker_id
        self.kernel = kernel
        self.runtime = runtime
        self.lanes = list(lanes)
        self.heartbeat_enabled = heartbeat_enabled
        self.submit_shutdown_timeout_s = submit_shutdown_timeout_s
        self._shutdown = asyncio.Event()

    def request_shutdown(self) -> None:
        self._shutdown.set()

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
                hb = await self.kernel.heartbeat(attempt)
                ctx.extend_lease()
                if hb.get("cancel_requested"):
                    ctx.fenced.set()
                    return
            except Fenced:
                ctx.fenced.set()
                return
            except Exception:
                log.warning("heartbeat failed for %s", attempt["attempt_id"], exc_info=True)

    async def run_once(self) -> str:
        attempt = await self.kernel.claim(self.worker_id, self.lanes)
        if attempt is None:
            return "idle"

        fenced = asyncio.Event()
        ctx = AttemptContext(attempt, self.kernel, fenced)
        stop = asyncio.Event()
        beat_task: asyncio.Task | None = None
        if self.heartbeat_enabled:
            beat_task = asyncio.create_task(self._heartbeat_loop(attempt, ctx, stop))

        runtime_task = asyncio.create_task(self._run_attempt(attempt, ctx))
        try:
            while not runtime_task.done():
                if fenced.is_set():
                    runtime_task.cancel()
                await asyncio.sleep(0.02)
            try:
                outcome = await runtime_task
            except asyncio.CancelledError:
                return "fenced"
            except Fenced:
                return "fenced"
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

            if fenced.is_set():
                return "fenced"
            ctx.check()
            try:
                await asyncio.wait_for(
                    asyncio.shield(self.kernel.submit_result(attempt, outcome)),
                    timeout=self.submit_shutdown_timeout_s,
                )
            except asyncio.TimeoutError:
                log.warning("submit timed out during shutdown for %s", attempt["attempt_id"])
                return "fenced"
            except Fenced:
                return "fenced"
            return "submitted"
        finally:
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
        poll = 1.0
        poll_max = 5.0
        while not self._shutdown.is_set():
            try:
                result = await self.run_once()
            except AuthFailed:
                log.error("worker token rejected; exiting")
                raise SystemExit(1) from None
            if result == "idle":
                try:
                    await asyncio.wait_for(self._shutdown.wait(), timeout=poll)
                    break
                except asyncio.TimeoutError:
                    poll = min(poll * 1.5, poll_max)
                continue
            poll = 1.0
