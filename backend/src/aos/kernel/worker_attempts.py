"""Worker protocol: claim, heartbeat, fail, end and budget settlement (M1-BE-05-A)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from psycopg import AsyncConnection, errors as pg_errors
from . import ids, tasks as task_ops
from .admission import AdmissionContext, check_admission, count_live_seat_attempts
from .instances import _load_definitions, _pack_meta, _seat_limits
from .outbox import ExecutionEventWrite, OutboxRow, append_outbox_many, write_execution_event
from .worker_fence import CommittedFenced, require_claimed_attempt, write_attempt_fenced


class WorkerError(Exception):
    def __init__(self, code: str, status: int, title: str, detail: str = "", **extra: Any) -> None:
        self.code = code
        self.status = status
        self.title = title
        self.detail = detail
        self.extra = extra
        super().__init__(title)


@dataclass(frozen=True)
class EndAttemptResult:
    ended: bool
    fenced: CommittedFenced | None = None


@dataclass(frozen=True)
class ExpireOutcome:
    expired: bool
    readmit: ExpiredLease | None = None


@dataclass(frozen=True)
class ExpiredLease:
    org_id: str
    seat_name: str
    seat_version: int
    workflow_name: str
    pack_version_id: str
    instance_id: str
    task_id: str
    turn_id: str | None
    attempts_used: int
    max_attempts: int
    contract: dict[str, Any]
    attributes: dict[str, Any]
    task_state: str


def _usage_cost(usage: dict[str, Any], *, reserve_if_empty: bool, reserved_usd: float) -> float:
    raw = usage.get("cost_usd")
    if raw is None or raw == "":
        return reserved_usd if reserve_if_empty else 0.0
    return float(raw)


async def settle_attempt_budget(
    conn: AsyncConnection,
    *,
    org_id: str,
    instance_id: str,
    seat: str,
    task_id: str,
    attempt_id: str,
    correlation_id: str,
    reserved_usd: float,
    actual_usd: float,
) -> None:
    settled_increment = min(actual_usd, reserved_usd)
    if actual_usd > reserved_usd + 1e-9:
        await write_execution_event(
            conn,
            ExecutionEventWrite(
                org_id=org_id,
                run_id=instance_id,
                event_type="BudgetExceeded",
                actor_kind="kernel",
                actor_id="kernel",
                correlation_id=correlation_id,
                redacted_summary="Attempt usage exceeded its reservation.",
                task_id=task_id,
                attempt_id=attempt_id,
                attributes={"limit": reserved_usd, "used": actual_usd},
            ),
        )
    await conn.execute(
        "update gov.budget_ledger"
        " set reserved_usd = reserved_usd - %s, settled_usd = settled_usd + %s"
        " where org_id = %s and seat = %s and day = current_date",
        (reserved_usd, settled_increment, org_id, seat),
    )


async def end_claimed_attempt(
    conn: AsyncConnection,
    *,
    org_id: str,
    attempt_id: str,
    worker_id: str,
    fencing_token: int,
    outcome: str,
    failure_class: str | None = None,
    reserve_if_empty: bool = False,
) -> EndAttemptResult:
    gate = await require_claimed_attempt(
        conn, org_id=org_id, attempt_id=attempt_id, worker_id=worker_id, fencing_token=fencing_token
    )
    if isinstance(gate, CommittedFenced):
        return EndAttemptResult(ended=False, fenced=gate)

    cur = await conn.execute(
        "update work.attempts"
        " set state = 'ENDED', outcome = %s, ended_at = now(), failure_class = %s"
        " where id = %s and state = 'CLAIMED'"
        " returning reserved_usd, usage",
        (outcome, failure_class, attempt_id),
    )
    row = await cur.fetchone()
    if row is None:
        fenced = await write_attempt_fenced(
            conn,
            org_id=gate.org_id,
            instance_id=gate.instance_id,
            task_id=gate.task_id,
            attempt_id=attempt_id,
            correlation_id=gate.correlation_id,
            worker_id=worker_id,
            proposed_token=fencing_token,
            current_token=gate.fencing_token,
        )
        return EndAttemptResult(ended=False, fenced=fenced)

    reserved_usd, usage = float(row[0]), row[1]
    usage_doc = usage if isinstance(usage, dict) else {}
    actual = _usage_cost(usage_doc, reserve_if_empty=reserve_if_empty, reserved_usd=reserved_usd)
    await settle_attempt_budget(
        conn,
        org_id=gate.org_id,
        instance_id=gate.instance_id,
        seat=gate.seat,
        task_id=gate.task_id,
        attempt_id=attempt_id,
        correlation_id=gate.correlation_id,
        reserved_usd=reserved_usd,
        actual_usd=actual,
    )
    await append_outbox_many(
        conn,
        [
            OutboxRow(
                stream=ids.stream_instance(gate.instance_id),
                event_type="attempt.ended",
                instance_id=gate.instance_id,
                audience={"roles": ["buyer"]},
                data={
                    "instance_id": gate.instance_id,
                    "task_id": gate.task_id,
                    "attempt_id": attempt_id,
                    "outcome": outcome,
                },
            )
        ],
    )
    return EndAttemptResult(ended=True)


async def claim_next_attempt(
    conn: AsyncConnection,
    *,
    org_id: str,
    worker_id: str,
    lanes: list[str],
    lease_seconds: float,
) -> dict[str, Any] | None:
    cur = await conn.execute(
        "select a.id, a.task_id, a.n, a.fencing_token, a.turn_id, a.resume,"
        " t.instance_id, t.kind, t.contract"
        " from work.attempts a"
        " join work.tasks t on t.id = a.task_id"
        " join work.instances i on i.id = t.instance_id"
        " where a.state = 'ADMITTED' and i.org_id = %s and t.kind = any(%s)"
        " order by a.admitted_at"
        " for update of a skip locked"
        " limit 1",
        (org_id, lanes),
    )
    row = await cur.fetchone()
    if row is None:
        return None
    (
        attempt_id,
        task_id,
        n,
        fencing_token,
        turn_id,
        resume,
        instance_id,
        kind,
        contract_json,
    ) = row
    lease_until = datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)
    await conn.execute(
        "update work.attempts"
        " set state = 'CLAIMED', worker_id = %s, claimed_at = now(), lease_expires_at = %s"
        " where id = %s and state = 'ADMITTED'",
        (worker_id, lease_until, attempt_id),
    )
    contract = contract_json if isinstance(contract_json, dict) else json.loads(contract_json)
    icur = await conn.execute(
        "select correlation_id from work.instances where id = %s",
        (instance_id,),
    )
    inst = await icur.fetchone()
    correlation_id = inst[0] if inst else attempt_id
    await write_execution_event(
        conn,
        ExecutionEventWrite(
            org_id=org_id,
            run_id=instance_id,
            event_type="TaskDispatched",
            actor_kind="kernel",
            actor_id="kernel",
            correlation_id=correlation_id,
            redacted_summary=f"Attempt {attempt_id} claimed by worker.",
            task_id=task_id,
            attempt_id=attempt_id,
            attributes={"attempt_id": attempt_id, "n": int(n), "fencing_token": int(fencing_token)},
        ),
    )
    await append_outbox_many(
        conn,
        [
            OutboxRow(
                stream=ids.stream_instance(instance_id),
                event_type="attempt.started",
                instance_id=instance_id,
                audience={"roles": ["buyer"]},
                data={
                    "instance_id": instance_id,
                    "task_id": task_id,
                    "attempt_id": attempt_id,
                    "n": int(n),
                },
            )
        ],
    )
    payload: dict[str, Any] = {
        "attempt_id": attempt_id,
        "task_id": task_id,
        "instance_id": instance_id,
        "n": int(n),
        "fencing_token": int(fencing_token),
        "lease_seconds": int(lease_seconds),
        "kind": kind,
        "contract": contract,
        "turn_id": turn_id,
        "resume": resume,
    }
    return payload


async def heartbeat(
    conn: AsyncConnection,
    *,
    org_id: str,
    attempt_id: str,
    worker_id: str,
    fencing_token: int,
    lease_seconds: float,
) -> dict[str, Any] | CommittedFenced:
    gate = await require_claimed_attempt(
        conn, org_id=org_id, attempt_id=attempt_id, worker_id=worker_id, fencing_token=fencing_token
    )
    if isinstance(gate, CommittedFenced):
        return gate
    lease_until = datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)
    await conn.execute(
        "update work.attempts set lease_expires_at = %s where id = %s and state = 'CLAIMED'",
        (lease_until, attempt_id),
    )
    return {"lease_expires_at": lease_until.isoformat().replace("+00:00", "Z"), "cancel_requested": False}


def load_skill_instructions(packs_dir: Path, contract: dict[str, Any]) -> str:
    pack = contract.get("pack") or {}
    pack_name = pack.get("name")
    skill = (contract.get("skill") or {}).get("name")
    if not pack_name or not skill:
        raise WorkerError("internal", 500, "Contract is incomplete", "Missing pack or skill on the frozen contract.")
    root = packs_dir / str(pack_name) / "skills" / str(skill)
    rel = "instructions.md"
    path = root / rel
    if not path.is_file():
        raise WorkerError(
            "conflict",
            409,
            "Skill instructions missing",
            f"Instructions file for skill {skill!r} is not on disk.",
        )
    return path.read_text(encoding="utf-8")


async def get_contract(
    conn: AsyncConnection,
    *,
    org_id: str,
    attempt_id: str,
    worker_id: str,
    fencing_token: int,
    packs_dir: Path,
) -> dict[str, Any] | CommittedFenced:
    gate = await require_claimed_attempt(
        conn, org_id=org_id, attempt_id=attempt_id, worker_id=worker_id, fencing_token=fencing_token
    )
    if isinstance(gate, CommittedFenced):
        return gate
    instructions = load_skill_instructions(packs_dir, gate.contract)
    return {"contract": gate.contract, "skill_instructions": instructions}


async def fail_attempt(
    conn: AsyncConnection,
    *,
    org_id: str,
    attempt_id: str,
    worker_id: str,
    fencing_token: int,
    failure_class: str,
    message: str,
) -> EndAttemptResult:
    gate = await require_claimed_attempt(
        conn, org_id=org_id, attempt_id=attempt_id, worker_id=worker_id, fencing_token=fencing_token
    )
    if isinstance(gate, CommittedFenced):
        return EndAttemptResult(ended=False, fenced=gate)

    end = await end_claimed_attempt(
        conn,
        org_id=org_id,
        attempt_id=attempt_id,
        worker_id=worker_id,
        fencing_token=fencing_token,
        outcome="failed",
        failure_class=failure_class,
        reserve_if_empty=False,
    )
    if not end.ended:
        return end

    await write_execution_event(
        conn,
        ExecutionEventWrite(
            org_id=gate.org_id,
            run_id=gate.instance_id,
            event_type="TaskFailed",
            actor_kind="kernel",
            actor_id="kernel",
            correlation_id=gate.correlation_id,
            redacted_summary=message[:400],
            task_id=gate.task_id,
            attempt_id=attempt_id,
            attributes={"failure_category": failure_class},
        ),
    )
    retryable = failure_class in ("model_error", "tool_timeout")
    if retryable and gate.attempts_used < gate.max_attempts:
        await conn.execute(
            "update work.tasks set state = 'RUNNING', updated_at = now() where id = %s",
            (gate.task_id,),
        )
    else:
        await conn.execute(
            "update work.tasks set state = 'EXCEPTION', updated_at = now() where id = %s",
            (gate.task_id,),
        )
    return end


async def expire_one_attempt(conn: AsyncConnection, *, attempt_id: str | None = None) -> ExpireOutcome:
    """End one expired lease. Re-admission runs in a separate transaction (see scheduler)."""
    if attempt_id is None:
        pick = await conn.execute(
            "select id from work.attempts"
            " where state = 'CLAIMED' and lease_expires_at <= now()"
            " order by lease_expires_at"
            " for update skip locked"
            " limit 1",
        )
        picked = await pick.fetchone()
        if picked is None:
            return ExpireOutcome(expired=False)
        attempt_id = picked[0]

    cur = await conn.execute(
        "select a.id, a.task_id, a.turn_id, a.worker_id, a.fencing_token, a.reserved_usd, a.usage,"
        " t.instance_id, i.org_id, i.seat, i.seat_version, i.workflow, i.pack_version_id, i.attributes,"
        " i.correlation_id, t.attempts_used, t.max_attempts, t.contract, t.state"
        " from work.attempts a"
        " join work.tasks t on t.id = a.task_id"
        " join work.instances i on i.id = t.instance_id"
        " where a.id = %s and a.state = 'CLAIMED' and a.lease_expires_at <= now()"
        " for update of a, t",
        (attempt_id,),
    )
    row = await cur.fetchone()
    if row is None:
        return ExpireOutcome(expired=False)
    (
        _aid,
        task_id,
        turn_id,
        _worker_id,
        _fencing_token,
        reserved_usd,
        usage,
        instance_id,
        org_id,
        seat_name,
        seat_version,
        workflow_name,
        pvid,
        attributes,
        correlation_id,
        attempts_used,
        max_attempts,
        contract_json,
        task_state,
    ) = row
    usage_doc = usage if isinstance(usage, dict) else {}
    ended = await conn.execute(
        "update work.attempts"
        " set state = 'ENDED', outcome = 'expired', ended_at = now()"
        " where id = %s and state = 'CLAIMED'"
        " returning id",
        (attempt_id,),
    )
    if await ended.fetchone() is None:
        return ExpireOutcome(expired=False)

    actual = _usage_cost(usage_doc, reserve_if_empty=True, reserved_usd=float(reserved_usd))
    await settle_attempt_budget(
        conn,
        org_id=org_id,
        instance_id=instance_id,
        seat=seat_name,
        task_id=task_id,
        attempt_id=attempt_id,
        correlation_id=correlation_id,
        reserved_usd=float(reserved_usd),
        actual_usd=actual,
    )
    await conn.execute(
        "update work.tasks set fencing_token = fencing_token + 1, updated_at = now() where id = %s",
        (task_id,),
    )
    await append_outbox_many(
        conn,
        [
            OutboxRow(
                stream=ids.stream_instance(instance_id),
                event_type="attempt.ended",
                instance_id=instance_id,
                audience={"roles": ["buyer"]},
                data={
                    "instance_id": instance_id,
                    "task_id": task_id,
                    "attempt_id": attempt_id,
                    "outcome": "expired",
                },
            )
        ],
    )
    contract = contract_json if isinstance(contract_json, dict) else json.loads(contract_json)
    attributes = attributes if isinstance(attributes, dict) else json.loads(attributes or "{}")

    if task_state != "RUNNING" or int(attempts_used) >= int(max_attempts):
        return ExpireOutcome(expired=True)

    return ExpireOutcome(
        expired=True,
        readmit=ExpiredLease(
        org_id=org_id,
        seat_name=seat_name,
        seat_version=int(seat_version),
        workflow_name=workflow_name,
        pack_version_id=str(pvid),
        instance_id=instance_id,
        task_id=task_id,
        turn_id=turn_id,
        attempts_used=int(attempts_used),
        max_attempts=int(max_attempts),
        contract=contract,
        attributes=attributes,
        task_state=task_state,
        ),
    )


async def readmit_after_expiry(
    conn: AsyncConnection,
    *,
    org_id: str,
    seat_name: str,
    seat_version: int,
    workflow_name: str,
    pack_version_id: str,
    instance_id: str,
    task_id: str,
    turn_id: str | None,
    attempts_used: int,
    max_attempts: int,
    contract: dict[str, Any],
    attributes: dict[str, Any],
) -> None:
    """Separate transaction from expiry: seat lock, admission gates, admit (same order as postTurn)."""
    scur = await conn.execute(
        "select state from registry.seats"
        " where org_id = %s and name = %s and version = %s for update",
        (org_id, seat_name, seat_version),
    )
    seat_row = await scur.fetchone()
    if seat_row is None:
        return
    seat_state = seat_row[0]

    await conn.execute("select id from work.tasks where id = %s for update", (task_id,))

    pack_name, _, _, pack_status = await _pack_meta(conn, org_id, pack_version_id)
    live = await count_live_seat_attempts(conn, org_id, seat_name)
    reservation = float((contract.get("budget") or {}).get("cost_usd", 0.0))
    ctx = AdmissionContext(
        org_id=org_id,
        actor="kernel",
        actor_roles=["kernel"],
        seat_name=seat_name,
        seat_state=seat_state,
        workflow_name=workflow_name,
        instance_id=instance_id,
        pack_version_id=pack_version_id,
        pack_published=pack_status == "published",
        task_id=task_id,
        attempts_used=attempts_used,
        max_attempts=max_attempts,
        has_live_attempt=False,
        dependency_versions=attributes,
        contract_dependency_versions=contract.get("dependency_versions") or {},
        reservation_usd=reservation,
        participant_ok=True,
        live_seat_attempts=live,
    )
    refusal = await check_admission(conn, ctx)
    if refusal:
        return

    seat_doc = (await _load_definitions(conn, pack_version_id)).get("Seat", {}).get(seat_name) or {}
    daily_limit = float(_seat_limits(seat_doc)["daily_cost_usd"])
    new_attempt_id = ids.new_attempt_id()
    attempt_n = attempts_used + 1
    try:
        await task_ops.admit_attempt(
            conn,
            org_id=org_id,
            seat=seat_name,
            daily_limit_usd=daily_limit,
            task_id=task_id,
            attempt_id=new_attempt_id,
            turn_id=turn_id,
            attempt_n=attempt_n,
            reservation_usd=reservation,
        )
        if turn_id:
            await conn.execute(
                "update work.turns set attempt_id = %s where id = %s",
                (new_attempt_id, turn_id),
            )
    except (pg_errors.CheckViolation, pg_errors.UniqueViolation):
        return


async def readmit_after_expiry_lease(conn: AsyncConnection, lease: ExpiredLease) -> None:
    await readmit_after_expiry(
        conn,
        org_id=lease.org_id,
        seat_name=lease.seat_name,
        seat_version=lease.seat_version,
        workflow_name=lease.workflow_name,
        pack_version_id=lease.pack_version_id,
        instance_id=lease.instance_id,
        task_id=lease.task_id,
        turn_id=lease.turn_id,
        attempts_used=lease.attempts_used,
        max_attempts=lease.max_attempts,
        contract=lease.contract,
        attributes=lease.attributes,
    )

