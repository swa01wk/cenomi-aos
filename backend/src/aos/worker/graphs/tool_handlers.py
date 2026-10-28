"""Shared tool-call handling for assist and task graphs."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from ..draft_body import build_save_draft_body
from ..errors import AttemptWaitingForInput, Fenced, ToolInvocationError
from ..protocol import AttemptContext, AttemptFailed
from ..untrusted import already_observed

KERNEL_DRAFT_TOOLS = frozenset({"save_draft", "ask_question"})


def order_tool_calls(pending: list[dict[str, Any]], *, defer_ask: bool = True) -> list[dict[str, Any]]:
    """Non-ask tools in model order, then the first ask_question."""
    if not defer_ask:
        return list(pending)
    first_ask = next(
        (i for i, tc in enumerate(pending) if str(tc.get("name") or "") == "ask_question"),
        None,
    )
    if first_ask is None:
        return list(pending)
    non_ask = [tc for tc in pending if str(tc.get("name") or "") != "ask_question"]
    return non_ask + [pending[first_ask]]


def split_submit_calls(pending: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    submit = next((tc for tc in pending if str(tc.get("name") or "") == "submit"), None)
    rest = [tc for tc in pending if str(tc.get("name") or "") != "submit"]
    return rest, submit


async def execute_tool_calls(
    *,
    ctx: AttemptContext,
    contract: dict[str, Any],
    envelope: dict[str, Any],
    pending: list[dict[str, Any]],
    kernel_tools: frozenset[str],
    saved: dict[str, dict[str, Any]],
    counts: dict[str, int],
    actions: list[str],
    worker_notes: list[str],
    skip_tool_names: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """Run one model step's tool calls. May set ended_needs_input."""
    notes = list(worker_notes)
    ended_needs_input = False
    observed: list[dict[str, Any]] = list(envelope.get("tool_observations") or [])
    ordered = order_tool_calls(pending)
    if defer_ask_with_connectors(ordered, kernel_tools):
        ordered = [tc for tc in ordered if str(tc.get("name") or "") != "ask_question"]
        notes.append(
            "ask_question was held because other tools ran in the same step. Read their results, save the draft, "
            "then ask only what is still missing."
        )
    for tc in ordered:
        ctx.check()
        if ctx.attempt_closed:
            break
        name = str(tc.get("name") or "")
        if name in skip_tool_names:
            continue
        args = tc.get("args") if isinstance(tc.get("args"), dict) else {}
        if name not in kernel_tools:
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
                notes.append(
                    f"save_draft skipped: same content as the v{same.get('version')} you saved in this reply."
                )
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
                    "content_hash": saved_row.get("content_hash"),
                    "args_sha": args_sha,
                    "content": body["content"],
                }
                actions.append(
                    f"save_draft: saved {at} v{saved_row.get('version')}. The requester can see it; don't save it "
                    "again unless something changed. Next, ask for what is still missing or reply."
                )
            elif name == "ask_question":
                questions_raw = args.get("questions")
                questions = [str(q) for q in questions_raw] if isinstance(questions_raw, list) else []
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
    return {
        "worker_notes": notes,
        "actions_this_reply": actions,
        "draft_422_counts": counts,
        "saved_in_attempt": saved,
        "ended_needs_input": ended_needs_input,
    }


def defer_ask_with_connectors(pending: list[dict[str, Any]], kernel_tools: frozenset[str]) -> bool:
    return any(str(tc.get("name") or "") not in kernel_tools for tc in pending) and any(
        str(tc.get("name") or "") == "ask_question" for tc in pending
    )
