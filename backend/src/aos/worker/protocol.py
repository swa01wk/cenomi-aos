"""Worker protocol: claim, heartbeat, runtime, submit or fail."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Protocol

from .errors import Fenced
from .failure import fail_attempt_classes
from .types import AgentResult, WorkerAttempt


class KernelClient(Protocol):
    async def claim(self, worker_id: str, lanes: list[str]) -> WorkerAttempt | None: ...
    async def heartbeat(self, attempt: WorkerAttempt) -> dict[str, Any]: ...
    async def get_contract(self, attempt: WorkerAttempt) -> dict[str, Any]: ...
    async def assemble_context(self, attempt: WorkerAttempt, *, reason: str) -> dict[str, Any]: ...
    async def post_events(
        self,
        attempt: WorkerAttempt,
        *,
        events: list[dict[str, Any]] | None = None,
        stream: list[dict[str, Any]] | None = None,
    ) -> None: ...
    async def call_tool(self, attempt: WorkerAttempt, tool: str, args: dict[str, Any]) -> dict[str, Any]: ...
    async def save_draft(self, attempt: WorkerAttempt, body: dict[str, Any]) -> dict[str, Any]: ...
    async def ask_questions(
        self,
        attempt: WorkerAttempt,
        *,
        blocks: list[dict[str, Any]],
        questions: list[str] | None = None,
    ) -> dict[str, Any]: ...
    async def submit_result(self, attempt: WorkerAttempt, result: AgentResult) -> dict[str, Any]: ...
    async def fail_attempt(self, attempt: WorkerAttempt, failure_class: str, message: str) -> None: ...


class AttemptFailed(Exception):
    def __init__(self, failure_class: str, message: str):
        if failure_class not in fail_attempt_classes():
            raise ValueError(failure_class)
        super().__init__(message)
        self.failure_class = failure_class


class AttemptContext:
    """Kernel calls for one attempt; respects local and remote fencing."""

    def __init__(
        self,
        attempt: WorkerAttempt,
        kernel: KernelClient,
        fenced: asyncio.Event,
        *,
        ignore_local_lease_deadline: bool = False,
    ):
        self.attempt = attempt
        self.kernel = kernel
        self.fenced = fenced
        self._ignore_local_lease = ignore_local_lease_deadline
        self._local_deadline = time.monotonic() + float(attempt["lease_seconds"])
        self.contract_bundle: dict[str, Any] | None = None
        self.envelope: dict[str, Any] | None = None
        self.agent_started = False
        self.attempt_closed = False
        self._usage = {
            "tokens_in": 0,
            "tokens_out": 0,
            "cost_usd": 0.0,
            "time_s": 0.0,
            "steps": 0,
            "actions": 0,
        }
        self._started_at = time.monotonic()

    def extend_lease(self, *, heartbeat_sent_at: float | None = None) -> None:
        base = heartbeat_sent_at if heartbeat_sent_at is not None else time.monotonic()
        self._local_deadline = base + float(self.attempt["lease_seconds"])

    def lease_expired(self) -> bool:
        if self._ignore_local_lease:
            return False
        if time.monotonic() >= self._local_deadline:
            self.fenced.set()
            return True
        return False

    def check(self) -> None:
        if self.fenced.is_set():
            raise Fenced(self.attempt["attempt_id"])
        if not self._ignore_local_lease and time.monotonic() >= self._local_deadline:
            self.fenced.set()
            raise Fenced(self.attempt["attempt_id"])

    async def post_events(self, **kwargs: Any) -> None:
        self.check()
        await self.kernel.post_events(self.attempt, **kwargs)

    async def get_contract(self) -> dict[str, Any]:
        self.check()
        return await self.kernel.get_contract(self.attempt)

    async def assemble_context(self, *, reason: str) -> dict[str, Any]:
        self.check()
        return await self.kernel.assemble_context(self.attempt, reason=reason)

    async def call_tool(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        self.check()
        return await self.kernel.call_tool(self.attempt, tool, args)

    async def save_draft(self, body: dict[str, Any]) -> dict[str, Any]:
        self.check()
        return await self.kernel.save_draft(self.attempt, body)

    async def ask_questions(
        self,
        blocks: list[dict[str, Any]],
        questions: list[str] | None = None,
    ) -> dict[str, Any]:
        self.check()
        result = await self.kernel.ask_questions(self.attempt, blocks=blocks, questions=questions)
        self.attempt_closed = True
        return result

    async def submit_result(self, result: AgentResult) -> dict[str, Any]:
        self.check()
        return await self.kernel.submit_result(self.attempt, result)

    def record_model_usage(self, tokens_in: int, tokens_out: int, cost_usd: float | None) -> None:
        self._usage["tokens_in"] = int(self._usage["tokens_in"]) + int(tokens_in)
        self._usage["tokens_out"] = int(self._usage["tokens_out"]) + int(tokens_out)
        if cost_usd is not None:
            self._usage["cost_usd"] = float(self._usage["cost_usd"]) + float(cost_usd)
        self._usage["steps"] = int(self._usage["steps"]) + 1

    def record_tool_action(self) -> None:
        self._usage["actions"] = int(self._usage["actions"]) + 1

    def consumed_budget(self) -> dict[str, Any]:
        elapsed = max(0.0, time.monotonic() - self._started_at)
        out = dict(self._usage)
        out["time_s"] = float(out.get("time_s") or 0) + elapsed
        return out
