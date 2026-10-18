"""AgentRuntime adapters: ScriptedRuntime (tests), FakeRuntime and LangGraphRuntime (assist graph)."""

from __future__ import annotations

import logging
import os
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Protocol

from .models import load_model_registry_config, validate_real_model_startup
from .protocol import AttemptContext
from .types import AgentResult, WorkerAttempt

if TYPE_CHECKING:
    from .checkpointer import CheckpointerHandle

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
):
    resolved = await checkpointer.resolve(attempt)
    if resolved.fresh_after_missing_checkpoint:
        await ctx.post_events(
            events=[{"event_type": "AgentStarted", "redacted_summary": _MISSING_CHECKPOINT_SUMMARY}],
        )
        await ctx.assemble_context(reason="start")
        return resolved
    if is_resume and resolved.checkpoint_id:
        await ctx.assemble_context(reason="resume")
    return resolved


class ScriptedRuntime:
    """Ordered async steps for protocol tests; not the production assist graph."""

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
            raise RuntimeError("ScriptedRuntime had no steps")
        return result


class FakeRuntime:
    """Same assist graph as production, with a scripted FakeChatModel."""

    def __init__(
        self,
        *,
        checkpointer: CheckpointerHandle,
        script: str | None = None,
    ):
        self._checkpointer = checkpointer
        self._script = script

    def _script_name(self) -> str:
        return (self._script or os.environ.get("AOS_FAKE_SCRIPT") or "assist.stream.yaml").strip()

    async def start(self, attempt: WorkerAttempt, ctx: AttemptContext) -> AgentResult:
        resolved = await _prepare_checkpoint_thread(attempt, ctx, self._checkpointer, is_resume=False)
        return await self._run_graph(attempt, ctx, resolved)

    async def resume(self, attempt: WorkerAttempt, ctx: AttemptContext) -> AgentResult:
        resolved = await _prepare_checkpoint_thread(attempt, ctx, self._checkpointer, is_resume=True)
        return await self._run_graph(attempt, ctx, resolved)

    async def _run_graph(self, attempt: WorkerAttempt, ctx: AttemptContext, resolved) -> AgentResult:
        from .fake_chat import chat_model_from_script
        from .graph_runner import run_assist_graph
        from .scripts_loader import load_fake_script

        script = load_fake_script(self._script_name())
        model = chat_model_from_script(script)
        return await run_assist_graph(
            attempt=attempt,
            ctx=ctx,
            chat_model=model,
            checkpointer=self._checkpointer,
            resolved=resolved,
            adapter="fake",
        )


class LangGraphRuntime:
    """Assist graph with the configured provider chat model."""

    def __init__(self, *, checkpointer: CheckpointerHandle):
        self._checkpointer = checkpointer
        self._cfg = load_model_registry_config()
        self._resolved = validate_real_model_startup(self._cfg)

    async def start(self, attempt: WorkerAttempt, ctx: AttemptContext) -> AgentResult:
        resolved = await _prepare_checkpoint_thread(attempt, ctx, self._checkpointer, is_resume=False)
        return await self._run_graph(attempt, ctx, resolved)

    async def resume(self, attempt: WorkerAttempt, ctx: AttemptContext) -> AgentResult:
        resolved = await _prepare_checkpoint_thread(attempt, ctx, self._checkpointer, is_resume=True)
        return await self._run_graph(attempt, ctx, resolved)

    async def _run_graph(self, attempt: WorkerAttempt, ctx: AttemptContext, resolved) -> AgentResult:
        from .graph_runner import run_assist_graph
        from .models import build_chat_model

        contract = attempt.get("contract") or {}
        model = build_chat_model(self._resolved, contract, self._cfg)
        return await run_assist_graph(
            attempt=attempt,
            ctx=ctx,
            chat_model=model,
            checkpointer=self._checkpointer,
            resolved=resolved,
            adapter="langgraph",
            resolved_model=self._resolved,
            model_cfg=self._cfg,
        )
