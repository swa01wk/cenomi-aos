"""Run the compiled assist graph for one attempt."""

from __future__ import annotations

from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel

from .checkpointer import CheckpointerHandle, ResolvedThread
from .errors import Fenced
from .graphs.assist import build_assist_graph
from .graphs.state import AssistGraphState
from .models import ModelRegistryConfig, ResolvedModel
from .protocol import AttemptContext
from .types import AgentResult, WorkerAttempt


async def run_assist_graph(
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
    graph = build_assist_graph(checkpointer=checkpointer.saver)
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
    config = {"configurable": configurable}
    initial: AssistGraphState = {
        "ids": {"turn_id": str(attempt.get("turn_id") or "")},
        "worker_notes": [],
        "draft_422_counts": {},
        "stream_seq": 0,
    }
    try:
        if resolved.checkpoint_id:
            final = await graph.ainvoke(None, config)
        else:
            final = await graph.ainvoke(initial, config)
    except Fenced:
        raise
    result = final.get("agent_result")
    if not isinstance(result, dict):
        raise RuntimeError("assist graph ended without agent_result")
    return result  # type: ignore[return-value]
