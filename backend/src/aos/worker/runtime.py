"""AgentRuntime adapters (fake for tests, LangGraph skeleton for M1-AG-02)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol

from .protocol import AttemptContext
from .types import AgentResult, WorkerAttempt

RuntimeStep = Callable[[WorkerAttempt, AttemptContext], Awaitable[AgentResult]]


class AgentRuntime(Protocol):
    async def start(self, attempt: WorkerAttempt, ctx: AttemptContext) -> AgentResult: ...
    async def resume(self, attempt: WorkerAttempt, ctx: AttemptContext) -> AgentResult: ...


class FakeRuntime:
    """Runs an ordered list of async steps; the last step's return value wins."""

    def __init__(self, steps: list[RuntimeStep]):
        self._steps = list(steps)

    async def start(self, attempt: WorkerAttempt, ctx: AttemptContext) -> AgentResult:
        return await self._run(attempt, ctx)

    async def resume(self, attempt: WorkerAttempt, ctx: AttemptContext) -> AgentResult:
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

    async def start(self, attempt: WorkerAttempt, ctx: AttemptContext) -> AgentResult:
        raise NotImplementedError("LangGraphRuntime is not wired until M1-AG-02 (set AOS_RUNTIME=fake)")

    async def resume(self, attempt: WorkerAttempt, ctx: AttemptContext) -> AgentResult:
        raise NotImplementedError("LangGraphRuntime is not wired until M1-AG-02 (set AOS_RUNTIME=fake)")
