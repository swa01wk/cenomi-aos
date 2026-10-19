"""postAttemptEvents: execution events, usage accumulation, stream deltas (M1-BE-05-B)."""

from __future__ import annotations

from typing import Any

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from ..sse import OutboxHub
from .outbox import ExecutionEventWrite, write_execution_event
from .worker_attempts import (
    EndAttemptResult,
    emit_task_state_changed,
    end_claimed_attempt,
    merge_usage,
)
from .worker_fence import ClaimedAttempt, CommittedFenced, require_claimed_attempt

_ALLOWED = frozenset({"AgentStarted", "ModelInvoked", "ToolRequested", "CheckpointSaved"})


def _gateway_tools(contract: dict[str, Any]) -> frozenset[str]:
    """Tools the worker calls through the kernel's tool gateway, which counts them against budget.actions itself."""
    return frozenset(
        str(g.get("name"))
        for g in contract.get("allowed_tools") or []
        if isinstance(g, dict) and g.get("kind") in ("connector", "compute")
    )


def _merge_event_usage(
    usage: dict[str, Any],
    event_type: str,
    attributes: dict[str, Any],
    gateway_tools: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    out = dict(usage)
    if event_type == "ModelInvoked":
        out["tokens_in"] = int(out.get("tokens_in") or 0) + int(attributes.get("tokens_in") or 0)
        out["tokens_out"] = int(out.get("tokens_out") or 0) + int(attributes.get("tokens_out") or 0)
        raw_cost = attributes.get("cost_usd")
        if raw_cost is not None:
            out["cost_usd"] = float(out.get("cost_usd") or 0) + float(raw_cost)
        out["steps"] = int(out.get("steps") or 0) + 1
    elif event_type == "ToolRequested" and str(attributes.get("tool") or "") not in gateway_tools:
        # Kernel tools (save_draft, ask_question) count here. Gateway tools count when the gateway authorizes the
        # call, so counting their request too would spend two actions per call.
        out["actions"] = int(out.get("actions") or 0) + 1
    return out


def _budget_exceeded(contract: dict[str, Any], usage: dict[str, Any]) -> tuple[str, Any, Any] | None:
    budget = contract.get("budget") or {}
    tokens = int(budget.get("tokens") or 0)
    used_tokens = int(usage.get("tokens_in") or 0) + int(usage.get("tokens_out") or 0)
    if tokens and used_tokens > tokens:
        return ("tokens", tokens, used_tokens)
    steps = int(budget.get("steps") or 0)
    used_steps = int(usage.get("steps") or 0)
    if steps and used_steps > steps:
        return ("steps", steps, used_steps)
    cost_limit = float(budget.get("cost_usd") or 0)
    used_cost = float(usage.get("cost_usd") or 0)
    if cost_limit and used_cost > cost_limit + 1e-9:
        return ("cost_usd", cost_limit, used_cost)
    return None


async def _delta_recipient(conn: AsyncConnection, gate: ClaimedAttempt) -> str | None:
    if gate.turn_id:
        cur = await conn.execute(
            "select author_kind, author_id from work.turns where id = %s",
            (gate.turn_id,),
        )
        row = await cur.fetchone()
        if row and row[0] == "person":
            return str(row[1])
    on_behalf = gate.contract.get("on_behalf_of") or {}
    person_id = on_behalf.get("person_id")
    return str(person_id) if person_id else None


async def post_attempt_events(
    conn: AsyncConnection,
    *,
    org_id: str,
    attempt_id: str,
    worker_id: str,
    fencing_token: int,
    events: list[dict[str, Any]] | None,
    stream: list[dict[str, Any]] | None,
    hub: OutboxHub,
) -> CommittedFenced | EndAttemptResult | None:
    gate = await require_claimed_attempt(
        conn, org_id=org_id, attempt_id=attempt_id, worker_id=worker_id, fencing_token=fencing_token
    )
    if isinstance(gate, CommittedFenced):
        return gate

    usage = dict(gate.usage)
    gateway_tools = _gateway_tools(gate.contract)
    budget_crossed: tuple[str, Any, Any] | None = None
    for ev in events or []:
        event_type = ev.get("event_type")
        if event_type not in _ALLOWED:
            from .worker_attempts import WorkerError

            raise WorkerError(
                "validation_failed",
                422,
                "Event type not allowed",
                f"{event_type!r} cannot be proposed by the worker.",
            )
        summary = str(ev.get("redacted_summary") or "")[:400]
        attrs = ev.get("attributes") if isinstance(ev.get("attributes"), dict) else {}
        await write_execution_event(
            conn,
            ExecutionEventWrite(
                org_id=gate.org_id,
                run_id=gate.instance_id,
                event_type=event_type,
                actor_kind="seat",
                actor_id=gate.seat,
                correlation_id=gate.correlation_id,
                redacted_summary=summary,
                task_id=gate.task_id,
                attempt_id=attempt_id,
                attributes=attrs,
            ),
        )
        usage = _merge_event_usage(usage, event_type, attrs, gateway_tools)
        crossed = _budget_exceeded(gate.contract, usage)
        if crossed:
            budget_crossed = crossed
            break

    await conn.execute(
        "update work.attempts set usage = %s where id = %s",
        (Jsonb(usage), attempt_id),
    )

    if stream:
        from .worker_attempts import WorkerError

        if not gate.turn_id:
            raise WorkerError(
                "validation_failed",
                422,
                "Turn required for stream",
                "This attempt has no turn to stream against.",
            )
        for chunk in stream:
            if str(chunk.get("turn_id")) != gate.turn_id:
                raise WorkerError(
                    "validation_failed",
                    422,
                    "Wrong turn for stream",
                    "stream turn_id must match the attempt's turn.",
                )

    recipient = await _delta_recipient(conn, gate)
    if stream and recipient:
        for chunk in stream:
            await hub.publish_delta(
                instance_id=gate.instance_id,
                turn_id=str(chunk["turn_id"]),
                delta_seq=int(chunk["seq"]),
                text=str(chunk["text"]),
                recipient_person_id=recipient,
            )

    if budget_crossed is None:
        return None

    limit_name, limit_val, used_val = budget_crossed
    await write_execution_event(
        conn,
        ExecutionEventWrite(
            org_id=gate.org_id,
            run_id=gate.instance_id,
            event_type="BudgetExceeded",
            actor_kind="kernel",
            actor_id="kernel",
            correlation_id=gate.correlation_id,
            redacted_summary="Attempt crossed its budget limit.",
            task_id=gate.task_id,
            attempt_id=attempt_id,
            attributes={"limit": limit_name, "used": used_val, "budget": limit_val},
        ),
    )
    from_state = gate.task_state
    end = await end_claimed_attempt(
        conn,
        org_id=org_id,
        attempt_id=attempt_id,
        worker_id=worker_id,
        fencing_token=fencing_token,
        outcome="failed",
        failure_class="budget_exhausted",
        reserve_if_empty=False,
    )
    if end.ended:
        await conn.execute(
            "update work.tasks set state = 'EXCEPTION', updated_at = now() where id = %s",
            (gate.task_id,),
        )
        if from_state != "EXCEPTION":
            tcur = await conn.execute("select template from work.tasks where id = %s", (gate.task_id,))
            trow = await tcur.fetchone()
            template = trow[0] if trow else gate.contract.get("template", "assist")
            await emit_task_state_changed(
                conn,
                instance_id=gate.instance_id,
                task_id=gate.task_id,
                template=template,
                from_state=from_state,
                to_state="EXCEPTION",
            )
        if gate.kind == "assist":
            from .reply_failure import post_reply_failed

            await post_reply_failed(
                conn,
                org_id=gate.org_id,
                instance_id=gate.instance_id,
                seat=gate.seat,
                seat_version=gate.seat_version,
                attempt_id=attempt_id,
                failure_class="budget_exhausted",
            )
        await write_execution_event(
            conn,
            ExecutionEventWrite(
                org_id=gate.org_id,
                run_id=gate.instance_id,
                event_type="TaskFailed",
                actor_kind="kernel",
                actor_id="kernel",
                correlation_id=gate.correlation_id,
                redacted_summary="Attempt stopped: budget exhausted.",
                task_id=gate.task_id,
                attempt_id=attempt_id,
                attributes={"failure_category": "budget_exhausted"},
            ),
        )
    return end
