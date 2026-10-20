"""Eight admission gates (M1) and budget reservation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from psycopg import AsyncConnection

from . import audit_store, ids
from .refusal import CommittedRefusal

MAX_LIVE_ATTEMPTS_PER_SEAT = 4

GATE_RULE_PREFIX = "admission.gate"


def _dependency_versions_match(contract_deps: dict, instance_attrs: dict) -> bool:
    for key, expected in contract_deps.items():
        if instance_attrs.get(key) != expected:
            return False
    return True


@dataclass(frozen=True)
class AdmissionContext:
    org_id: str
    actor: str
    actor_roles: list[str]
    seat_name: str
    seat_state: str
    workflow_name: str
    instance_id: str | None
    pack_version_id: str
    pack_published: bool
    task_id: str | None
    attempts_used: int
    max_attempts: int
    has_live_attempt: bool
    dependency_versions: dict[str, Any]
    contract_dependency_versions: dict[str, Any]
    reservation_usd: float
    participant_ok: bool
    live_seat_attempts: int
    turn_attempts_used: int | None = None


def _rule(gate: int, code: str) -> str:
    return f"{GATE_RULE_PREFIX}.{gate}.{code}"


async def _record_admission_denied(
    conn: AsyncConnection,
    ctx: AdmissionContext,
    *,
    code: str,
    rule: str,
    title: str,
    detail: str,
    status: int = 403,
) -> CommittedRefusal:
    decision_id = ids.new_decision_id()
    if ctx.instance_id:
        subject_kind = "instance"
        subject_id = ctx.instance_id
    else:
        subject_kind = "seat"
        subject_id = ctx.seat_name
    await conn.execute(
        "insert into gov.decision_records ("
        " id, org_id, subject_kind, subject_id, event, value, actor, actor_role"
        ") values (%s, %s, %s, %s, 'admission.denied', %s, %s, %s)",
        (
            decision_id,
            ctx.org_id,
            subject_kind,
            subject_id,
            code,
            ctx.actor,
            ctx.actor_roles[0] if ctx.actor_roles else None,
        ),
    )
    await audit_store.record(
        conn,
        org_id=ctx.org_id,
        actor=ctx.actor,
        action="admission.denied",
        subject=f"{subject_kind}:{subject_id}",
        data={"code": code, "rule": rule, "decision_id": decision_id},
    )
    return CommittedRefusal(code, status, title, detail, decision_id, rule=rule)


@dataclass(frozen=True)
class AdmissionFailure:
    code: str
    rule: str
    title: str
    detail: str
    status: int = 403


async def evaluate_admission(conn: AsyncConnection, ctx: AdmissionContext) -> AdmissionFailure | None:
    """Run gates 1–8 without writing refusal records."""
    # Gate 1: kill switch — table arrives in M4 (docs/specs/backend/ddl/0006_m4_govern.sql).
    if ctx.seat_state != "ACTIVE":
        return AdmissionFailure(
            "seat_not_active",
            _rule(2, "seat_not_active"),
            "This agent is not available",
            "The seat must be active before starting or continuing work.",
        )
    if not ctx.pack_published:
        return AdmissionFailure(
            "conflict",
            _rule(3, "pack_not_published"),
            "Pack version is not published",
            "This job's pack version is not published.",
            status=409,
        )
    if not ctx.participant_ok:
        return AdmissionFailure(
            "not_permitted",
            _rule(4, "not_permitted"),
            "You may not do that here",
            "You are not allowed to act on this job.",
        )
    if ctx.has_live_attempt:
        return AdmissionFailure(
            "conflict",
            _rule(5, "live_attempt"),
            "An attempt is already running",
            "Wait for the current attempt to finish before starting another.",
            status=409,
        )
    budget_used = (
        ctx.turn_attempts_used
        if ctx.turn_attempts_used is not None
        else ctx.attempts_used
    )
    if budget_used >= ctx.max_attempts:
        return AdmissionFailure(
            "conflict",
            _rule(5, "attempts_exhausted"),
            "No attempts left",
            "This task has used all allowed attempts.",
            status=409,
        )
    if not _dependency_versions_match(ctx.contract_dependency_versions, ctx.dependency_versions):
        return AdmissionFailure(
            "stale_version",
            _rule(6, "stale_version"),
            "Inputs changed",
            "Reload the job and try again.",
            status=409,
        )
    if not await _budget_fits(conn, ctx.org_id, ctx.seat_name, ctx.reservation_usd):
        return AdmissionFailure(
            "budget_exhausted",
            _rule(7, "budget_exhausted"),
            "Daily budget reached",
            "This seat has no budget left for new attempts today.",
        )
    if ctx.live_seat_attempts >= MAX_LIVE_ATTEMPTS_PER_SEAT:
        return AdmissionFailure(
            "unavailable",
            _rule(8, "unavailable"),
            "Seat is busy",
            "Too many attempts are running on this seat. Try again shortly.",
            status=503,
        )
    return None


async def check_admission(
    conn: AsyncConnection,
    ctx: AdmissionContext,
    *,
    record_denial: bool = True,
) -> CommittedRefusal | None:
    """Run gates 1–8 in order. Returns a committed refusal or None if all pass."""
    fail = await evaluate_admission(conn, ctx)
    if fail is None:
        return None
    if not record_denial:
        return CommittedRefusal(
            fail.code, fail.status, fail.title, fail.detail, "", rule=fail.rule
        )
    return await _record_admission_denied(
        conn,
        ctx,
        code=fail.code,
        rule=fail.rule,
        title=fail.title,
        detail=fail.detail,
        status=fail.status,
    )


async def _budget_fits(conn: AsyncConnection, org_id: str, seat: str, reservation_usd: float) -> bool:
    cur = await conn.execute(
        "select limit_usd, reserved_usd, settled_usd from gov.budget_ledger"
        " where org_id = %s and seat = %s and day = current_date",
        (org_id, seat),
    )
    row = await cur.fetchone()
    if row is None:
        return True
    limit_usd, reserved, settled = float(row[0]), float(row[1]), float(row[2])
    return reserved + settled + reservation_usd <= limit_usd + 1e-9


async def refuse_budget_exhausted(conn: AsyncConnection, ctx: AdmissionContext) -> CommittedRefusal:
    return await _record_admission_denied(
        conn,
        ctx,
        code="budget_exhausted",
        rule=_rule(7, "budget_exhausted"),
        title="Daily budget reached",
        detail="This seat has no budget left for new attempts today.",
    )


async def refuse_live_attempt_conflict(conn: AsyncConnection, ctx: AdmissionContext) -> CommittedRefusal:
    return await _record_admission_denied(
        conn,
        ctx,
        code="conflict",
        rule=_rule(5, "live_attempt"),
        title="An attempt is already running",
        detail="Wait for the current attempt to finish before starting another.",
        status=409,
    )


async def reserve_budget(
    conn: AsyncConnection,
    *,
    org_id: str,
    seat: str,
    daily_limit_usd: float,
    reservation_usd: float,
) -> None:
    await conn.execute(
        "insert into gov.budget_ledger (org_id, seat, day, limit_usd, reserved_usd, settled_usd)"
        " values (%s, %s, current_date, %s, %s, 0)"
        " on conflict (org_id, seat, day) do update"
        " set reserved_usd = gov.budget_ledger.reserved_usd + excluded.reserved_usd",
        (org_id, seat, daily_limit_usd, reservation_usd),
    )


async def count_live_seat_attempts(conn: AsyncConnection, org_id: str, seat: str) -> int:
    cur = await conn.execute(
        "select count(*) from work.attempts a"
        " join work.tasks t on t.id = a.task_id"
        " join work.instances i on i.id = t.instance_id"
        " where i.org_id = %s and i.seat = %s and a.state in ('ADMITTED', 'CLAIMED')",
        (org_id, seat),
    )
    row = await cur.fetchone()
    return int(row[0]) if row else 0


async def task_has_live_attempt(conn: AsyncConnection, task_id: str) -> bool:
    cur = await conn.execute(
        "select 1 from work.attempts where task_id = %s and state in ('ADMITTED', 'CLAIMED') limit 1",
        (task_id,),
    )
    return await cur.fetchone() is not None
