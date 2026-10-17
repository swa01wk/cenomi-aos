"""AgentRuntime adapters (fake for tests, LangGraph skeleton for M1-AG-02)."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Protocol

from .checkpointer import CheckpointerHandle
from .protocol import AttemptContext
from .types import AgentResult, WorkerAttempt

log = logging.getLogger("aos.worker.runtime")

RuntimeStep = Callable[[WorkerAttempt, AttemptContext], Awaitable[AgentResult]]

_MISSING_CHECKPOINT_SUMMARY = (
    "Checkpoint missing; starting a fresh thread from the assembled context."
)


class AgentRuntime(Protocol):
    async def start(self, attempt: WorkerAttempt, ctx: AttemptContext) -> AgentResult: ...
    async def resume(self, attempt: WorkerAttempt, ctx: AttemptContext) -> AgentResult: ...


async def _prepare_checkpoint_thread(
    attempt: WorkerAttempt,
    ctx: AttemptContext,
    checkpointer: CheckpointerHandle,
    *,
    is_resume: bool,
) -> None:
    resolved = await checkpointer.resolve(attempt)
    if resolved.fresh_after_missing_checkpoint:
        await ctx.post_events(
            events=[{"event_type": "AgentStarted", "redacted_summary": _MISSING_CHECKPOINT_SUMMARY}],
        )
        await ctx.assemble_context(reason="start")
        return
    if is_resume and resolved.checkpoint_id:
        await ctx.assemble_context(reason="resume")


class FakeRuntime:
    """Runs an ordered list of async steps; the last step's return value wins."""

    def __init__(
        self,
        steps: list[RuntimeStep],
        *,
        checkpointer: CheckpointerHandle | None = None,
    ):
        self._steps = list(steps)
        self._checkpointer = checkpointer

    async def start(self, attempt: WorkerAttempt, ctx: AttemptContext) -> AgentResult:
        if self._checkpointer is not None:
            await _prepare_checkpoint_thread(attempt, ctx, self._checkpointer, is_resume=False)
        return await self._run(attempt, ctx)

    async def resume(self, attempt: WorkerAttempt, ctx: AttemptContext) -> AgentResult:
        if self._checkpointer is not None:
            await _prepare_checkpoint_thread(attempt, ctx, self._checkpointer, is_resume=True)
        return await self._run(attempt, ctx)

    async def _run(self, attempt: WorkerAttempt, ctx: AttemptContext) -> AgentResult:
        result: AgentResult | None = None
        for step in self._steps:
            result = await step(attempt, ctx)
        if result is None:
            raise RuntimeError("FakeRuntime had no steps")
        return result


class LangGraphRuntime:
    """Skeleton only — graph and model arrive in M1-AG-02."""

    def __init__(self, *, checkpointer: CheckpointerHandle | None = None):
        self._checkpointer = checkpointer

    async def start(self, attempt: WorkerAttempt, ctx: AttemptContext) -> AgentResult:
        if self._checkpointer is not None:
            await _prepare_checkpoint_thread(attempt, ctx, self._checkpointer, is_resume=False)
        raise NotImplementedError("LangGraphRuntime is not wired until M1-AG-02 (set AOS_RUNTIME=fake)")

    async def resume(self, attempt: WorkerAttempt, ctx: AttemptContext) -> AgentResult:
        if self._checkpointer is not None:
            await _prepare_checkpoint_thread(attempt, ctx, self._checkpointer, is_resume=True)
        raise NotImplementedError("LangGraphRuntime is not wired until M1-AG-02 (set AOS_RUNTIME=fake)")
