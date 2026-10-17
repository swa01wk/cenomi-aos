"""Committed refusals: Decision Record + audit in the same transaction, then Problem response."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from psycopg import AsyncConnection

from . import audit_store, ids


@dataclass(frozen=True)
class CommittedRefusal:
    code: str
    status: int
    title: str
    detail: str
    decision_id: str
    rule: str | None = None


async def record_context_denied(
    conn: AsyncConnection,
    *,
    org_id: str,
    instance_id: str,
    actor: str,
    actor_role: str | None,
    rule: str,
    audit_data: dict[str, Any],
) -> str:
    """Record context.denied on the contract instance; no artifact_ref (cross-job ids stay in audit only)."""
    decision_id = ids.new_decision_id()
    await conn.execute(
        "insert into gov.decision_records ("
        " id, org_id, subject_kind, subject_id, event, value, actor, actor_role"
        ") values (%s, %s, 'instance', %s, 'context.denied', 'not_permitted', %s, %s)",
        (decision_id, org_id, instance_id, actor, actor_role),
    )
    payload = {"rule": rule, "decision_id": decision_id, **audit_data}
    await audit_store.record(
        conn,
        org_id=org_id,
        actor=actor,
        action="context.denied",
        subject=f"instance:{instance_id}",
        data=payload,
    )
    return decision_id


async def record_tool_denied(
    conn: AsyncConnection,
    *,
    org_id: str,
    instance_id: str,
    task_id: str,
    attempt_id: str,
    correlation_id: str,
    seat: str,
    tool: str,
    code: str,
    rule: str,
    title: str,
    detail: str,
    status: int,
) -> CommittedRefusal:
    decision_id = ids.new_decision_id()
    await conn.execute(
        "insert into gov.decision_records ("
        " id, org_id, subject_kind, subject_id, event, value, actor, actor_role"
        ") values (%s, %s, 'instance', %s, 'tool.denied', %s, %s, %s)",
        (decision_id, org_id, instance_id, code, seat, None),
    )
    await audit_store.record(
        conn,
        org_id=org_id,
        actor=seat,
        action="tool.denied",
        subject=f"instance:{instance_id}",
        data={"tool": tool, "code": code, "rule": rule, "decision_id": decision_id},
    )
    from .outbox import ExecutionEventWrite, write_execution_event

    await write_execution_event(
        conn,
        ExecutionEventWrite(
            org_id=org_id,
            run_id=instance_id,
            event_type="ToolDenied",
            actor_kind="seat",
            actor_id=seat,
            correlation_id=correlation_id,
            redacted_summary=f"{tool} refused: {rule}",
            task_id=task_id,
            attempt_id=attempt_id,
            attributes={"tool": tool, "decision_id": decision_id, "rule": rule},
        ),
    )
    return CommittedRefusal(code, status, title, detail, decision_id, rule=rule)


async def refuse_context_viewer_not_participant(
    conn: AsyncConnection,
    *,
    org_id: str,
    instance_id: str,
    person_id: str,
    worker_id: str,
) -> CommittedRefusal:
    decision_id = await record_context_denied(
        conn,
        org_id=org_id,
        instance_id=instance_id,
        actor=person_id,
        actor_role=None,
        rule="on_behalf_of_not_participant",
        audit_data={"person_id": person_id, "worker_id": worker_id},
    )
    return CommittedRefusal(
        "not_permitted",
        403,
        "Cannot assemble context",
        "The on-behalf-of person is not a participant on this job.",
        decision_id,
        rule="on_behalf_of_not_participant",
    )
