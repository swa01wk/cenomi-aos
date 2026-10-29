"""Run the compiled graph for one attempt: the Task graph for task contracts, else the assist graph."""

from __future__ import annotations

from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel

from .checkpointer import CheckpointerHandle, ResolvedThread
from .errors import AttemptWaitingForInput, Fenced
from .graphs.state import AssistGraphState, TaskGraphState
from .models import ModelRegistryConfig, ResolvedModel
from .protocol import AttemptContext
from .types import AgentResult, WorkerAttempt


def _recursion_limit(contract: dict[str, Any]) -> int:
    steps = int((contract.get("budget") or {}).get("steps") or 0)
    if steps > 0:
        return 3 * steps + 5
    return 25


async def run_attempt_graph(
    *,
    attempt: WorkerAttempt,
    ctx: AttemptContext,
    chat_model: BaseChatModel,
    checkpointer: CheckpointerHandle,
    resolved: ResolvedThread,
    adapter: str,
    resolved_model: ResolvedModel | None = None,
    model_cfg: ModelRegistryConfig | None = None,
) -> AgentResult:
    contract = attempt.get("contract") or {}
    graph = checkpointer.assist_graph()
    configurable: dict[str, Any] = {
        "thread_id": resolved.thread_id,
        "ctx": ctx,
        "chat_model": chat_model,
        "attempt": attempt,
        "adapter": adapter,
        "resolved_model": resolved_model,
        "model_cfg": model_cfg,
    }
    if resolved.checkpoint_id:
        configurable["checkpoint_id"] = resolved.checkpoint_id
    config = {
        "configurable": configurable,
        "recursion_limit": _recursion_limit(contract),
    }
    initial: AssistGraphState = {
        "ids": {"turn_id": str(attempt.get("turn_id") or "")},
        "worker_notes": [],
        "actions_this_reply": [],
        "draft_422_counts": {},
        "stream_seq": 0,
        "saved_in_attempt": {},
    }
    try:
        if resolved.checkpoint_id:
            final = await graph.ainvoke(None, config)
        else:
            final = await graph.ainvoke(initial, config)
    except AttemptWaitingForInput:
        raise
    except Fenced:
        raise
    result = final.get("agent_result")
    if not isinstance(result, dict):
        raise RuntimeError(f"{contract.get('kind') or 'assist'} graph ended without agent_result")
    return result  # type: ignore[return-value]


async def run_task_graph(
    *,
    attempt: WorkerAttempt,
    ctx: AttemptContext,
    chat_model: BaseChatModel,
    checkpointer: CheckpointerHandle,
    resolved: ResolvedThread,
    adapter: str,
    resolved_model: ResolvedModel | None = None,
    model_cfg: ModelRegistryConfig | None = None,
) -> AgentResult:
    graph = checkpointer.task_graph()
    contract = attempt.get("contract") or {}
    configurable: dict[str, Any] = {
        "thread_id": resolved.thread_id,
        "ctx": ctx,
        "chat_model": chat_model,
        "attempt": attempt,
        "adapter": adapter,
        "resolved_model": resolved_model,
        "model_cfg": model_cfg,
    }
    if resolved.checkpoint_id:
        configurable["checkpoint_id"] = resolved.checkpoint_id
    config = {
        "configurable": configurable,
        "recursion_limit": _recursion_limit(contract),
    }
    initial: TaskGraphState = {
        "worker_notes": [],
        "actions_this_reply": [],
        "draft_422_counts": {},
        "saved_in_attempt": {},
    }
    try:
        if resolved.checkpoint_id:
            final = await graph.ainvoke(None, config)
        else:
            final = await graph.ainvoke(initial, config)
    except AttemptWaitingForInput:
        raise
    except Fenced:
        raise
    result = final.get("agent_result")
    if not isinstance(result, dict):
        raise RuntimeError("task graph ended without agent_result")
    return result  # type: ignore[return-value]
