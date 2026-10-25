"""Generic task LangGraph (M2-AG-01)."""

from __future__ import annotations

from typing import Any, Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from ..budget import require_model_budget
from ..errors import AttemptWaitingForInput, Fenced
from ..models import ModelRegistryConfig, ResolvedModel, compute_cost_usd
from ..prompt_render import render_context_message, render_task_system_message, task_prompt_version
from ..protocol import AttemptContext, AttemptFailed
from ..types import AgentResult, WorkerAttempt
from .assist import _attempt, _configurable, _ctx, _model_meta, _usage_from_message
from .state import TaskGraphState
from .tool_handlers import KERNEL_DRAFT_TOOLS, execute_tool_calls, split_submit_calls


async def load_node(state: TaskGraphState, config) -> dict[str, Any]:
    ctx = _ctx(config)
    ctx.check()
    bundle = await ctx.get_contract()
    contract = bundle.get("contract") if isinstance(bundle.get("contract"), dict) else {}
    expected = str(contract.get("contract_hash") or "")
    on_attempt = str(ctx.attempt.get("contract", {}).get("contract_hash") or "")
    if expected and on_attempt and expected != on_attempt:
        raise AttemptFailed("invalid_output", "Task contract hash does not match the admitted attempt.")
    ctx.contract_bundle = bundle
    if not ctx.agent_started:
        adapter = _configurable(config).get("adapter", "fake")
        await ctx.post_events(
            events=[
                {
                    "event_type": "AgentStarted",
                    "redacted_summary": "Task graph started.",
                    "attributes": {"adapter": adapter, "graph": "task"},
                }
            ]
        )
        ctx.agent_started = True
    reason = state.get("assemble_reason") or ("resume" if ctx.attempt.get("resume") else "start")
    return {"assemble_reason": reason}


async def assemble_context_node(state: TaskGraphState, config) -> dict[str, Any]:
    ctx = _ctx(config)
    ctx.check()
    reason = str(state.get("assemble_reason") or "start")
    envelope = await ctx.assemble_context(reason=reason)
    ctx.envelope = envelope
    return {"worker_notes": list(state.get("worker_notes") or []), "assemble_reason": "tool_result"}


async def model_step_node(state: TaskGraphState, config) -> dict[str, Any]:
    ctx = _ctx(config)
    ctx.check()
    envelope = ctx.envelope
    if not envelope:
        raise RuntimeError("assemble_context must run before model_step")
    require_model_budget(envelope)
    bundle = ctx.contract_bundle or {}
    contract = bundle.get("contract") if isinstance(bundle.get("contract"), dict) else ctx.attempt["contract"]
    skill = str(bundle.get("skill_instructions") or envelope.get("skill_instructions") or "")
    system = render_task_system_message(contract=contract, skill_instructions=skill, envelope=envelope)
    context = render_context_message(
        envelope=envelope,
        worker_notes=list(state.get("worker_notes") or []),
        actions_this_reply=list(state.get("actions_this_reply") or []),
    )
    messages = [SystemMessage(content=system), HumanMessage(content=context)]
    model = _configurable(config).get("chat_model")
    tools = envelope.get("commands") or []
    bound = model.bind_tools(tools) if tools else model
    try:
        ai = await bound.ainvoke(messages)
        ctx.check()
    except Fenced:
        raise
    if not isinstance(ai, AIMessage):
        ai = AIMessage(content=str(ai))
    tokens_in, tokens_out = _usage_from_message(ai)
    resolved, model_cfg = _model_meta(config)
    provider = resolved.provider if resolved else "fake"
    model_id = resolved.model_id if resolved else "fake"
    cost = compute_cost_usd(tokens_in, tokens_out, model_cfg) if model_cfg else 0.0
    if model_cfg and (not model_cfg.price_in_per_mtok or not model_cfg.price_out_per_mtok):
        cost_val = None
    else:
        cost_val = cost if (tokens_in or tokens_out) else 0.0
    await ctx.post_events(
        events=[
            {
                "event_type": "ModelInvoked",
                "redacted_summary": f"Model step ({model_id}).",
                "attributes": {
                    "provider": provider,
                    "model": model_id,
                    "prompt_version": task_prompt_version(),
                    "tokens_in": tokens_in,
                    "tokens_out": tokens_out,
                    "cost_usd": cost_val,
                },
            }
        ]
    )
    ctx.record_model_usage(tokens_in, tokens_out, cost_val)
    tool_calls = list(getattr(ai, "tool_calls", None) or [])
    return {
        "pending_tool_calls": tool_calls,
        "worker_notes": [],
    }


def _route_after_model(state: TaskGraphState) -> Literal["tools", "__invalid__"]:
    if state.get("pending_tool_calls"):
        return "tools"
    return "__invalid__"


async def invalid_output_node(state: TaskGraphState, config) -> dict[str, Any]:
    _ctx(config).check()
    raise AttemptFailed("invalid_output", "The model must call submit when the output is ready.")


async def tools_node(state: TaskGraphState, config) -> dict[str, Any]:
    ctx = _ctx(config)
    ctx.check()
    counts = dict(state.get("draft_422_counts") or {})
    saved = dict(state.get("saved_in_attempt") or {})
    contract = (ctx.contract_bundle or {}).get("contract") or ctx.attempt["contract"]
    envelope = ctx.envelope or {}
    rest, submit_call = split_submit_calls(list(state.get("pending_tool_calls") or []))
    batch = await execute_tool_calls(
        ctx=ctx,
        contract=contract,
        envelope=envelope,
        pending=rest,
        kernel_tools=KERNEL_DRAFT_TOOLS,
        saved=saved,
        counts=counts,
        actions=list(state.get("actions_this_reply") or []),
        worker_notes=list(state.get("worker_notes") or []),
    )
    out: dict[str, Any] = {
        "pending_tool_calls": [],
        "worker_notes": batch["worker_notes"],
        "actions_this_reply": batch["actions_this_reply"],
        "draft_422_counts": batch["draft_422_counts"],
        "saved_in_attempt": batch["saved_in_attempt"],
        "assemble_reason": "tool_result",
        "pending_submit": submit_call,
    }
    if batch.get("ended_needs_input"):
        out["ended_needs_input"] = True
    return out


def _route_after_tools(state: TaskGraphState) -> Literal["assemble_context", "needs_input", "finish"]:
    if state.get("ended_needs_input"):
        return "needs_input"
    if state.get("pending_submit"):
        return "finish"
    return "assemble_context"


async def needs_input_node(state: TaskGraphState, config) -> dict[str, Any]:
    _ctx(config).check()
    raise AttemptWaitingForInput()


def _output_refs(saved: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for row in saved.values():
        aid = row.get("artifact_id")
        ver = row.get("version")
        ch = row.get("content_hash")
        if aid and ver is not None and ch:
            refs.append({"artifact_id": str(aid), "version": int(ver), "content_hash": str(ch)})
    return refs


async def finish_node(state: TaskGraphState, config) -> dict[str, Any]:
    ctx = _ctx(config)
    ctx.check()
    attempt = _attempt(config)
    contract = (ctx.contract_bundle or {}).get("contract") or attempt["contract"]
    submit = state.get("pending_submit") or {}
    args = submit.get("args") if isinstance(submit.get("args"), dict) else {}
    summary = str(args.get("summary") or "").strip()
    if not summary:
        raise AttemptFailed("invalid_output", "submit requires a summary.")
    saved = dict(state.get("saved_in_attempt") or {})
    consumed = ctx.consumed_budget()
    result: AgentResult = {
        "schema_version": "aos.agent_result/1",
        "contract_id": contract["contract_id"],
        "attempt_id": attempt["attempt_id"],
        "status": "completed",
        "output_artifact_refs": _output_refs(saved),
        "evidence_refs": [],
        "input_versions": dict(contract.get("dependency_versions") or {}),
        "consumed_budget": consumed,
        "summary": (summary[:497] + "...") if len(summary) > 500 else summary,
    }
    return {"agent_result": result}


def build_task_graph(
    checkpointer: BaseCheckpointSaver | None = None,
    *,
    interrupt_after: list[str] | None = None,
) -> CompiledStateGraph:
    graph = StateGraph(TaskGraphState)
    graph.add_node("load", load_node)
    graph.add_node("assemble_context", assemble_context_node)
    graph.add_node("model_step", model_step_node)
    graph.add_node("tools", tools_node)
    graph.add_node("finish", finish_node)
    graph.add_node("needs_input", needs_input_node)
    graph.add_node("invalid_output", invalid_output_node)
    graph.add_edge(START, "load")
    graph.add_edge("load", "assemble_context")
    graph.add_edge("assemble_context", "model_step")
    graph.add_conditional_edges(
        "model_step",
        _route_after_model,
        {"tools": "tools", "__invalid__": "invalid_output"},
    )
    graph.add_conditional_edges(
        "tools",
        _route_after_tools,
        {"assemble_context": "assemble_context", "needs_input": "needs_input", "finish": "finish"},
    )
    graph.add_edge("needs_input", END)
    graph.add_edge("finish", END)
    return graph.compile(checkpointer=checkpointer, interrupt_after=interrupt_after or None)
