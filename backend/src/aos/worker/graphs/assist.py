"""Generic assist LangGraph (M1-AG-02)."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from ..budget import require_model_budget
from ..errors import Fenced, ToolInvocationError
from ..models import ModelRegistryConfig, ResolvedModel, compute_cost_usd
from ..prompt_render import prompt_version as assist_prompt_version
from ..protocol import AttemptContext, AttemptFailed
from ..prompt_render import render_context_message, render_system_message
from ..streaming import stream_text_deltas
from ..types import AgentResult, WorkerAttempt
from .state import AssistGraphState

log = logging.getLogger("aos.worker.graph.assist")

_COMPILED: dict[int, CompiledStateGraph] = {}


def _configurable(config) -> dict[str, Any]:
    return config.get("configurable") if isinstance(config, dict) else {}


def _ctx(config) -> AttemptContext:
    cfg = _configurable(config)
    ctx = cfg.get("ctx")
    if ctx is None:
        raise RuntimeError("assist graph missing AttemptContext in configurable.ctx")
    return ctx


def _chat_model(config):
    return _configurable(config).get("chat_model")


def _attempt(config) -> WorkerAttempt:
    return _configurable(config)["attempt"]


def _model_meta(config) -> tuple[ResolvedModel | None, ModelRegistryConfig | None]:
    cfg = _configurable(config)
    return cfg.get("resolved_model"), cfg.get("model_cfg")


def _tool_class(contract: dict[str, Any], tool_name: str) -> str | None:
    for entry in contract.get("allowed_tools") or []:
        if isinstance(entry, dict) and entry.get("name") == tool_name:
            return str(entry.get("class") or "")
    return None


async def load_node(state: AssistGraphState, config) -> dict[str, Any]:
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
                    "redacted_summary": "Assist graph started.",
                    "attributes": {"adapter": adapter, "graph": "assist"},
                }
            ]
        )
        ctx.agent_started = True
    turn_id = str(ctx.attempt.get("turn_id") or "")
    ids = dict(state.get("ids") or {})
    if turn_id:
        ids["turn_id"] = turn_id
    reason = state.get("assemble_reason") or ("resume" if ctx.attempt.get("resume") else "start")
    return {"ids": ids, "assemble_reason": reason}


async def assemble_context_node(state: AssistGraphState, config) -> dict[str, Any]:
    ctx = _ctx(config)
    ctx.check()
    reason = str(state.get("assemble_reason") or "start")
    envelope = await ctx.assemble_context(reason=reason)
    ctx.envelope = envelope
    return {"worker_notes": list(state.get("worker_notes") or []), "assemble_reason": "tool_result"}


async def model_step_node(state: AssistGraphState, config) -> dict[str, Any]:
    ctx = _ctx(config)
    ctx.check()
    envelope = ctx.envelope
    if not envelope:
        raise RuntimeError("assemble_context must run before model_step")
    require_model_budget(envelope)
    bundle = ctx.contract_bundle or {}
    contract = bundle.get("contract") if isinstance(bundle.get("contract"), dict) else ctx.attempt["contract"]
    skill = str(bundle.get("skill_instructions") or envelope.get("skill_instructions") or "")
    system = render_system_message(contract=contract, skill_instructions=skill, envelope=envelope)
    context = render_context_message(envelope=envelope, worker_notes=list(state.get("worker_notes") or []))
    messages = [SystemMessage(content=system), HumanMessage(content=context)]
    model = _chat_model(config)
    tools = envelope.get("commands") or []
    bound = model.bind_tools(tools) if tools else model
    ai = await bound.ainvoke(messages)
    usage_meta = getattr(ai, "response_metadata", {}) or {}
    token_usage = usage_meta.get("token_usage") or usage_meta.get("usage") or {}
    tokens_in = int(token_usage.get("input_tokens") or token_usage.get("prompt_tokens") or 0)
    tokens_out = int(token_usage.get("output_tokens") or token_usage.get("completion_tokens") or 0)
    resolved, model_cfg = _model_meta(config)
    if tokens_in == 0 and tokens_out == 0 and hasattr(bound, "fake"):
        last = bound.fake._last  # noqa: SLF001
        turn_usage = last.usage if last and isinstance(last.usage, dict) else {}
        tokens_in = int(turn_usage.get("tokens_in") or 10)
        tokens_out = int(turn_usage.get("tokens_out") or 5)
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
                    "prompt_version": assist_prompt_version(),
                    "tokens_in": tokens_in,
                    "tokens_out": tokens_out,
                    "cost_usd": cost_val,
                },
            }
        ]
    )
    ctx.record_model_usage(tokens_in, tokens_out, cost_val)
    tool_calls = list(getattr(ai, "tool_calls", None) or [])
    text = ai.content if isinstance(ai.content, str) else str(ai.content or "")
    if tool_calls:
        return {
            "pending_tool_calls": tool_calls,
            "model_reply_text": "",
            "worker_notes": [],
        }
    return {
        "pending_tool_calls": [],
        "model_reply_text": text,
        "worker_notes": [],
    }


def _route_after_model(state: AssistGraphState) -> Literal["tools", "reply"]:
    if state.get("pending_tool_calls"):
        return "tools"
    return "reply"


async def tools_node(state: AssistGraphState, config) -> dict[str, Any]:
    ctx = _ctx(config)
    ctx.check()
    contract = (ctx.contract_bundle or {}).get("contract") or ctx.attempt["contract"]
    notes: list[str] = []
    counts = dict(state.get("draft_422_counts") or {})
    pending = list(state.get("pending_tool_calls") or [])
    for tc in pending:
        ctx.check()
        name = str(tc.get("name") or "")
        args = tc.get("args") if isinstance(tc.get("args"), dict) else {}
        await ctx.post_events(
            events=[
                {
                    "event_type": "ToolRequested",
                    "redacted_summary": f"Tool {name} requested.",
                    "attributes": {
                        "tool": name,
                        "args_sha256": hashlib.sha256(
                            json.dumps(args, sort_keys=True, separators=(",", ":")).encode()
                        ).hexdigest(),
                    },
                }
            ]
        )
        tool_class = _tool_class(contract, name)
        try:
            if name == "save_draft" or tool_class == "staged_write":
                await ctx.save_draft(args)
            else:
                await ctx.call_tool(name, args)
        except ToolInvocationError as exc:
            if exc.timed_out:
                raise AttemptFailed("tool_timeout", exc.message) from exc
            if exc.code == "policy_denied" or exc.rule:
                notes.append(f"not allowed: {exc.rule or exc.message}")
                continue
            if exc.code == "validation_failed":
                key = f"{name}:{json.dumps(args, sort_keys=True)}"
                n = int(counts.get(key) or 0) + 1
                counts[key] = n
                if n >= 2:
                    raise AttemptFailed("invalid_output", exc.message) from exc
                err_text = json.dumps(exc.errors or [], sort_keys=True)
                notes.append(f"validation failed for {name}: {err_text}")
                continue
            notes.append(str(exc.message))
            continue
        except Fenced:
            raise
    return {
        "pending_tool_calls": [],
        "worker_notes": notes,
        "draft_422_counts": counts,
        "assemble_reason": "tool_result",
    }


async def reply_node(state: AssistGraphState, config) -> dict[str, Any]:
    ctx = _ctx(config)
    ctx.check()
    attempt = _attempt(config)
    turn_id = str((state.get("ids") or {}).get("turn_id") or attempt.get("turn_id") or "")
    text = str(state.get("model_reply_text") or "")
    blocks = list(state.get("reply_blocks") or [])
    bound = _chat_model(config)
    if hasattr(bound, "fake") and bound.fake._last and bound.fake._last.reply_blocks:  # noqa: SLF001
        blocks = list(bound.fake._last.reply_blocks)
    if not blocks:
        # M1-AG-02: text-only replies. Typed chips/refusal blocks arrive in M1-AG-03.
        blocks = [{"kind": "text", "text": text}]
    chunks = []
    if hasattr(bound, "fake") and bound.fake._last and bound.fake._last.stream_chunks:  # noqa: SLF001
        chunks = list(bound.fake._last.stream_chunks)
    elif text:
        chunks = [text[i : i + 50] for i in range(0, len(text), 50)] if text else []
    seq = int(state.get("stream_seq") or 0)
    if turn_id and chunks:
        try:
            seq, streamed = await stream_text_deltas(ctx, turn_id=turn_id, seq_start=seq, chunks=chunks)
            if not text:
                text = streamed
                if blocks == [{"kind": "text", "text": ""}]:
                    blocks = [{"kind": "text", "text": text}]
        except Fenced:
            raise
    contract = (ctx.contract_bundle or {}).get("contract") or attempt["contract"]
    consumed = ctx.consumed_budget()
    result: AgentResult = {
        "schema_version": "aos.agent_result/1",
        "contract_id": contract["contract_id"],
        "attempt_id": attempt["attempt_id"],
        "status": "completed",
        "output_artifact_refs": [],
        "evidence_refs": [],
        "input_versions": dict(contract.get("dependency_versions") or {}),
        "consumed_budget": consumed,
        "summary": (text[:497] + "...") if len(text) > 500 else (text or "Completed assist turn."),
        "reply_blocks": blocks,
    }
    return {"stream_seq": seq, "agent_result": result, "reply_blocks": blocks}


def build_assist_graph(
    checkpointer: BaseCheckpointSaver | None = None,
    *,
    interrupt_after: list[str] | None = None,
) -> CompiledStateGraph:
    key = (id(checkpointer), tuple(interrupt_after or ()))
    if key in _COMPILED:
        return _COMPILED[key]
    graph = StateGraph(AssistGraphState)
    graph.add_node("load", load_node)
    graph.add_node("assemble_context", assemble_context_node)
    graph.add_node("model_step", model_step_node)
    graph.add_node("tools", tools_node)
    graph.add_node("reply", reply_node)
    graph.add_edge(START, "load")
    graph.add_edge("load", "assemble_context")
    graph.add_edge("assemble_context", "model_step")
    graph.add_conditional_edges("model_step", _route_after_model, {"tools": "tools", "reply": "reply"})
    graph.add_edge("tools", "assemble_context")
    graph.add_edge("reply", END)
    compiled = graph.compile(checkpointer=checkpointer, interrupt_after=interrupt_after or None)
    _COMPILED[key] = compiled
    return compiled
