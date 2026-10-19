"""Generic assist LangGraph (M1-AG-02)."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from ..budget import require_model_budget
from ..draft_body import build_save_draft_body
from ..errors import AttemptWaitingForInput, Fenced, ToolInvocationError
from ..models import ModelRegistryConfig, ResolvedModel, compute_cost_usd
from ..prompt_render import prompt_version as assist_prompt_version
from ..protocol import AttemptContext, AttemptFailed
from ..prompt_render import render_context_message, render_system_message
from ..streaming import LiveStreamBatcher
from ..untrusted import already_observed
from ..types import AgentResult, WorkerAttempt
from .state import AssistGraphState

log = logging.getLogger("aos.worker.graph.assist")


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


def _usage_from_message(msg: AIMessage) -> tuple[int, int]:
    meta = getattr(msg, "usage_metadata", None) or {}
    if isinstance(meta, dict):
        tin = int(meta.get("input_tokens") or 0)
        tout = int(meta.get("output_tokens") or 0)
        if tin or tout:
            return tin, tout
    resp = getattr(msg, "response_metadata", None) or {}
    usage = resp.get("token_usage") or resp.get("usage") or {}
    if isinstance(usage, dict):
        tin = int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
        tout = int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)
        return tin, tout
    return 0, 0


def _stream_chunk(raw: Any) -> Any:
    """Normalize LangChain stream items to message chunks."""
    if hasattr(raw, "message") and not hasattr(raw, "tool_call_chunks"):
        return raw.message
    return raw


async def _invoke_model_step(
    bound,
    messages: list,
    *,
    ctx: AttemptContext,
    turn_id: str,
    stream_seq: int,
) -> tuple[AIMessage, int]:
    saw_tool_chunks = False
    batcher: LiveStreamBatcher | None = None
    if turn_id:
        batcher = LiveStreamBatcher(ctx, turn_id=turn_id, seq_start=stream_seq)
    accumulated = None
    async for raw in bound.astream(messages):
        ctx.check()
        chunk = _stream_chunk(raw)
        tool_chunks = getattr(chunk, "tool_call_chunks", None) or []
        if tool_chunks:
            saw_tool_chunks = True
        if not saw_tool_chunks and batcher is not None:
            content = chunk.content
            if isinstance(content, str) and content:
                await batcher.push(content)
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, str) and part:
                        await batcher.push(part)
                    elif isinstance(part, dict) and part.get("type") == "text":
                        text = part.get("text")
                        if isinstance(text, str) and text:
                            await batcher.push(text)
        accumulated = chunk if accumulated is None else accumulated + chunk

    if batcher is not None and not saw_tool_chunks:
        stream_seq, _ = await batcher.finish()
    elif batcher is not None:
        stream_seq = batcher.seq

    if accumulated is None:
        return AIMessage(content=""), stream_seq
    if isinstance(accumulated, AIMessage):
        return accumulated, stream_seq
    return AIMessage(content=accumulated.content, tool_calls=getattr(accumulated, "tool_calls", None) or []), stream_seq


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
    context = render_context_message(
        envelope=envelope,
        worker_notes=list(state.get("worker_notes") or []),
        actions_this_reply=list(state.get("actions_this_reply") or []),
    )
    messages = [SystemMessage(content=system), HumanMessage(content=context)]
    model = _chat_model(config)
    tools = envelope.get("commands") or []
    bound = model.bind_tools(tools) if tools else model
    turn_id = str((state.get("ids") or {}).get("turn_id") or ctx.attempt.get("turn_id") or "")
    stream_seq = int(state.get("stream_seq") or 0)
    try:
        ai, stream_seq = await _invoke_model_step(
            bound,
            messages,
            ctx=ctx,
            turn_id=turn_id,
            stream_seq=stream_seq,
        )
    except Fenced:
        raise
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
            "stream_seq": stream_seq,
        }
    return {
        "pending_tool_calls": [],
        "model_reply_text": text,
        "worker_notes": [],
        "stream_seq": stream_seq,
    }


_KERNEL_TOOLS = frozenset({"save_draft", "ask_question"})


def _route_after_model(state: AssistGraphState) -> Literal["tools", "reply"]:
    if state.get("pending_tool_calls"):
        return "tools"
    return "reply"


def _order_tool_calls(pending: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """All non-ask tools in model order, then the first ask_question; drop further ask_question calls."""
    first_ask = next(
        (i for i, tc in enumerate(pending) if str(tc.get("name") or "") == "ask_question"),
        None,
    )
    if first_ask is None:
        return list(pending)
    non_ask = [tc for tc in pending if str(tc.get("name") or "") != "ask_question"]
    return non_ask + [pending[first_ask]]


async def tools_node(state: AssistGraphState, config) -> dict[str, Any]:
    ctx = _ctx(config)
    ctx.check()
    notes: list[str] = []
    counts = dict(state.get("draft_422_counts") or {})
    saved = dict(state.get("saved_in_attempt") or {})
    pending = _order_tool_calls(list(state.get("pending_tool_calls") or []))
    if any(str(tc.get("name") or "") not in _KERNEL_TOOLS for tc in pending) and any(
        str(tc.get("name") or "") == "ask_question" for tc in pending
    ):
        # Questions written alongside a lookup were written before its result: hold them, run the lookup, and let
        # the next step save what it learned and ask again.
        pending = [tc for tc in pending if str(tc.get("name") or "") != "ask_question"]
        notes.append(
            "ask_question was held because other tools ran in the same step. Read their results, save the draft, "
            "then ask only what is still missing."
        )
    contract = (ctx.contract_bundle or {}).get("contract") or ctx.attempt["contract"]
    envelope = ctx.envelope or {}
    observed: list[dict[str, Any]] = list(envelope.get("tool_observations") or [])
    actions: list[str] = list(state.get("actions_this_reply") or [])
    ended_needs_input = False
    for tc in pending:
        ctx.check()
        if ctx.attempt_closed:
            break
        name = str(tc.get("name") or "")
        args = tc.get("args") if isinstance(tc.get("args"), dict) else {}
        if name not in _KERNEL_TOOLS:
            # The model sees earlier calls only through observations; a repeat would spend an action for a
            # result it already has. Answer from the note instead of calling the tool again.
            if already_observed(observed, name, args):
                notes.append(
                    f"{name} was already called with {json.dumps(args, sort_keys=True)}; "
                    "its result is in tool_observations_rendered. Use it instead of calling again."
                )
                continue
            observed.append({"tool": name, "args": args})
        args_sha = hashlib.sha256(json.dumps(args, sort_keys=True).encode()).hexdigest()
        if name == "save_draft":
            same = next((v for v in saved.values() if v.get("args_sha") == args_sha), None)
            if same is not None:
                notes.append(f"save_draft skipped: same content as the v{same.get('version')} you saved in this reply.")
                continue
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
        try:
            if name == "save_draft":
                body = build_save_draft_body(
                    contract=contract,
                    envelope=envelope,
                    model_args=args,
                    saved_in_attempt=saved,
                )
                saved_row = await ctx.save_draft(body)
                at = str(body["artifact_type"])
                saved[at] = {
                    "artifact_id": saved_row.get("artifact_id"),
                    "version": saved_row.get("version"),
                    "args_sha": args_sha,
                }
                actions.append(
                    f"save_draft: saved {at} v{saved_row.get('version')}. The requester can see it; don't save it "
                    "again unless something changed. Next, ask for what is still missing or reply."
                )
            elif name == "ask_question":
                questions_raw = args.get("questions")
                questions = (
                    [str(q) for q in questions_raw]
                    if isinstance(questions_raw, list)
                    else []
                )
                preamble = str(args.get("preamble") or "").strip()
                blocks = [{"kind": "text", "text": preamble}] if preamble else []
                await ctx.ask_questions(blocks, questions=questions or None)
                ended_needs_input = True
                ctx.record_tool_action()
                break
            else:
                await ctx.call_tool(name, args)
                actions.append(f"{name}({json.dumps(args, sort_keys=True)}): result in tool_observations_rendered.")
            ctx.record_tool_action()
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
        except ValueError as exc:
            notes.append(str(exc))
            continue
        except Fenced:
            raise
    out: dict[str, Any] = {
        "pending_tool_calls": [],
        "worker_notes": notes,
        "actions_this_reply": actions,
        "draft_422_counts": counts,
        "saved_in_attempt": saved,
        "assemble_reason": "tool_result",
    }
    if ended_needs_input:
        out["ended_needs_input"] = True
    return out


def _route_after_tools(state: AssistGraphState) -> Literal["assemble_context", "needs_input"]:
    if state.get("ended_needs_input"):
        return "needs_input"
    return "assemble_context"


async def needs_input_node(state: AssistGraphState, config) -> dict[str, Any]:
    _ctx(config).check()
    raise AttemptWaitingForInput()


async def reply_node(state: AssistGraphState, config) -> dict[str, Any]:
    ctx = _ctx(config)
    ctx.check()
    attempt = _attempt(config)
    text = str(state.get("model_reply_text") or "")
    # M1-AG-02: text-only replies. Typed chips/refusal blocks arrive in M1-AG-03.
    blocks = [{"kind": "text", "text": text}]
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
    stream_seq = int(state.get("stream_seq") or 0)
    return {"stream_seq": stream_seq, "agent_result": result, "reply_blocks": blocks}


def build_assist_graph(
    checkpointer: BaseCheckpointSaver | None = None,
    *,
    interrupt_after: list[str] | None = None,
) -> CompiledStateGraph:
    graph = StateGraph(AssistGraphState)
    graph.add_node("load", load_node)
    graph.add_node("assemble_context", assemble_context_node)
    graph.add_node("model_step", model_step_node)
    graph.add_node("tools", tools_node)
    graph.add_node("reply", reply_node)
    graph.add_node("needs_input", needs_input_node)
    graph.add_edge(START, "load")
    graph.add_edge("load", "assemble_context")
    graph.add_edge("assemble_context", "model_step")
    graph.add_conditional_edges("model_step", _route_after_model, {"tools": "tools", "reply": "reply"})
    graph.add_conditional_edges(
        "tools",
        _route_after_tools,
        {"assemble_context": "assemble_context", "needs_input": "needs_input"},
    )
    graph.add_edge("needs_input", END)
    graph.add_edge("reply", END)
    return graph.compile(checkpointer=checkpointer, interrupt_after=interrupt_after or None)
