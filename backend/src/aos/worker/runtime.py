"""AgentRuntime adapters: ScriptedRuntime (tests), FakeRuntime and LangGraphRuntime."""

from __future__ import annotations

import logging
import os
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Protocol

from .models import load_model_registry_config, validate_real_model_startup
from .protocol import AttemptContext, AttemptFailed
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


def _attempt_kind(attempt: WorkerAttempt) -> str:
    contract = attempt.get("contract") if isinstance(attempt.get("contract"), dict) else {}
    return str(contract.get("kind") or "assist")


def _assist_fake_script(attempt: WorkerAttempt) -> str:
    """Pick a scripted reply for assist attempts: skill script, then env override, then generic stream."""
    from .scripts_loader import SCRIPTS_DIR

    contract = attempt.get("contract") if isinstance(attempt.get("contract"), dict) else {}
    skill = str((contract.get("skill") or {}).get("name") or "")
    scenario = os.environ.get("AOS_FAKE_SCENARIO", "happy").strip() or "happy"
    if skill:
        candidate = f"{skill}.{scenario}.yaml"
        if (SCRIPTS_DIR / candidate).is_file():
            return candidate
    env_script = os.environ.get("AOS_FAKE_SCRIPT", "").strip()
    if env_script:
        return env_script
    return "assist.stream.yaml"


def _fake_script_name(attempt: WorkerAttempt, explicit: str | None) -> str:
    if explicit and explicit.strip():
        return explicit.strip()
    kind = _attempt_kind(attempt)
    if kind == "assist":
        return _assist_fake_script(attempt)
    skill = (contract.get("skill") or {}).get("name") if isinstance(contract := attempt.get("contract"), dict) else None
    skill = str(skill or "unknown")
    scenario = os.environ.get("AOS_FAKE_SCENARIO", "happy").strip() or "happy"
    return f"{skill}.{scenario}.yaml"


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
    """Production graphs with a scripted FakeChatModel."""

    def __init__(
        self,
        *,
        checkpointer: CheckpointerHandle,
        script: str | None = None,
    ):
        self._checkpointer = checkpointer
        self._script = script

    async def start(self, attempt: WorkerAttempt, ctx: AttemptContext) -> AgentResult:
        resolved = await _prepare_checkpoint_thread(attempt, ctx, self._checkpointer, is_resume=False)
        return await self._run_graph(attempt, ctx, resolved)

    async def resume(self, attempt: WorkerAttempt, ctx: AttemptContext) -> AgentResult:
        resolved = await _prepare_checkpoint_thread(attempt, ctx, self._checkpointer, is_resume=True)
        return await self._run_graph(attempt, ctx, resolved)

    async def _run_graph(self, attempt: WorkerAttempt, ctx: AttemptContext, resolved) -> AgentResult:
        from .fake_chat import chat_model_from_script
        from .graph_runner import run_attempt_graph, run_task_graph
        from .scripts_loader import load_fake_script

        script_name = _fake_script_name(attempt, self._script)
        try:
            script = load_fake_script(script_name, attempt_n=int(attempt.get("n") or 1))
        except FileNotFoundError as exc:
            raise AttemptFailed(
                "model_error",
                f"No fake model script {script_name!r} for this attempt ({exc}).",
            ) from exc
        model = chat_model_from_script(script)
        kind = _attempt_kind(attempt)
        if kind == "task":
            return await run_task_graph(
                attempt=attempt,
                ctx=ctx,
                chat_model=model,
                checkpointer=self._checkpointer,
                resolved=resolved,
                adapter="fake",
            )
        return await run_attempt_graph(
            attempt=attempt,
            ctx=ctx,
            chat_model=model,
            checkpointer=self._checkpointer,
            resolved=resolved,
            adapter="fake",
        )


class LangGraphRuntime:
    """Assist or task graph with the configured provider chat model."""

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
        from .graph_runner import run_attempt_graph, run_task_graph
        from .models import build_chat_model

        contract = attempt.get("contract") or {}
        model = build_chat_model(self._resolved, contract, self._cfg)
        kind = _attempt_kind(attempt)
        if kind == "task":
            return await run_task_graph(
                attempt=attempt,
                ctx=ctx,
                chat_model=model,
                checkpointer=self._checkpointer,
                resolved=resolved,
                adapter="langgraph",
                resolved_model=self._resolved,
                model_cfg=self._cfg,
            )
        return await run_attempt_graph(
            attempt=attempt,
            ctx=ctx,
            chat_model=model,
            checkpointer=self._checkpointer,
            resolved=resolved,
            adapter="langgraph",
            resolved_model=self._resolved,
            model_cfg=self._cfg,
        )
