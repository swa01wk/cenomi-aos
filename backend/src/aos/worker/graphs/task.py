"""Generic Task LangGraph (M2-AG-01): the assist graph's steps, ending in submit instead of a reply."""

from __future__ import annotations

from typing import Any, Literal

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from ..types import AgentResult
from .assist import (
    _attempt,
    _ctx,
    _route_after_tools,
    assemble_context_node,
    load_node,
    model_step_node,
    needs_input_node,
    tools_node,
)
from .state import AssistGraphState

_SUMMARY_MAX = 500


def _route_after_model(state: AssistGraphState) -> Literal["tools", "finish"]:
    if state.get("pending_tool_calls"):
        return "tools"
    return "finish"


def output_refs(saved_in_attempt: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """The latest version of each artifact this attempt saved: what the Task proposes as its output."""
    refs: list[dict[str, Any]] = []
    for entry in saved_in_attempt.values():
        if entry.get("artifact_id") and entry.get("version") is not None and entry.get("content_hash"):
            refs.append(
                {
                    "artifact_id": str(entry["artifact_id"]),
                    "version": int(entry["version"]),
                    "content_hash": str(entry["content_hash"]),
                }
            )
    return refs


async def finish_node(state: AssistGraphState, config) -> dict[str, Any]:
    ctx = _ctx(config)
    ctx.check()
    attempt = _attempt(config)
    contract = (ctx.contract_bundle or {}).get("contract") or attempt["contract"]
    text = str(state.get("model_reply_text") or "").strip()
    if len(text) > _SUMMARY_MAX:
        text = text[: _SUMMARY_MAX - 3] + "..."
    result: AgentResult = {
        "schema_version": "aos.agent_result/1",
        "contract_id": contract["contract_id"],
        "attempt_id": attempt["attempt_id"],
        "status": "completed",
        "output_artifact_refs": output_refs(dict(state.get("saved_in_attempt") or {})),
        "evidence_refs": [],
        "input_versions": dict(contract.get("dependency_versions") or {}),
        "consumed_budget": ctx.consumed_budget(),
        "summary": text or f"Finished {contract.get('template') or 'the task'}.",
    }
    return {"agent_result": result}


def build_task_graph(
    checkpointer: BaseCheckpointSaver | None = None,
    *,
    interrupt_after: list[str] | None = None,
) -> CompiledStateGraph:
    graph = StateGraph(AssistGraphState)
    graph.add_node("load", load_node)
    graph.add_node("assemble_context", assemble_context_node)
    graph.add_node("model_step", model_step_node)
    graph.add_node("tools", tools_node)
    graph.add_node("finish", finish_node)
    graph.add_node("needs_input", needs_input_node)
    graph.add_edge(START, "load")
    graph.add_edge("load", "assemble_context")
    graph.add_edge("assemble_context", "model_step")
    graph.add_conditional_edges("model_step", _route_after_model, {"tools": "tools", "finish": "finish"})
    graph.add_conditional_edges(
        "tools",
        _route_after_tools,
        {"assemble_context": "assemble_context", "needs_input": "needs_input"},
    )
    graph.add_edge("needs_input", END)
    graph.add_edge("finish", END)
    return graph.compile(checkpointer=checkpointer, interrupt_after=interrupt_after or None)
