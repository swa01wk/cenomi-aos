"""Worker fencing: atomic row lock, AttemptFenced on refusal (M1-BE-05-A)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from psycopg import AsyncConnection

from .outbox import ExecutionEventWrite, write_execution_event


class WorkerFenceError(Exception):
    def __init__(self, code: str, status: int, title: str, detail: str = "", **extra: Any) -> None:
        self.code = code
        self.status = status
        self.title = title
        self.detail = detail
        self.extra = extra
        super().__init__(title)


@dataclass(frozen=True)
class CommittedFenced:
    """AttemptFenced is already committed; return problem_response, do not raise."""

    proposed_token: int
    current_token: int


@dataclass(frozen=True)
class ClaimedAttempt:
    attempt_id: str
    task_id: str
    instance_id: str
    org_id: str
    seat: str
    seat_version: int
    correlation_id: str
    fencing_token: int
    attempt_n: int
    turn_id: str | None
    kind: str
    contract: dict[str, Any]
    reserved_usd: float
    usage: dict[str, Any]
    worker_id: str
    task_state: str
    attempts_used: int
    max_attempts: int


async def write_attempt_fenced(
    conn: AsyncConnection,
    *,
    org_id: str,
    instance_id: str,
    task_id: str,
    attempt_id: str,
    correlation_id: str,
    worker_id: str,
    proposed_token: int,
    current_token: int,
) -> CommittedFenced:
    await write_execution_event(
        conn,
        ExecutionEventWrite(
            org_id=org_id,
            run_id=instance_id,
            event_type="AttemptFenced",
            actor_kind="worker",
            actor_id=worker_id,
            correlation_id=correlation_id,
            redacted_summary="Worker call refused: fencing token no longer valid.",
            task_id=task_id,
            attempt_id=attempt_id,
            attributes={"fencing_token": proposed_token, "current_token": current_token},
        ),
    )
    return CommittedFenced(proposed_token, current_token)


async def require_claimed_attempt(
    conn: AsyncConnection,
    *,
    org_id: str,
    attempt_id: str,
    worker_id: str,
    fencing_token: int,
) -> ClaimedAttempt | CommittedFenced:
    cur = await conn.execute(
        "select a.id, a.state, a.worker_id, a.fencing_token, a.task_id, a.n, a.turn_id, a.reserved_usd, a.usage,"
        " t.fencing_token, t.instance_id, t.kind, t.contract, t.state, t.attempts_used, t.max_attempts,"
        " i.org_id, i.seat, i.seat_version, i.correlation_id"
        " from work.attempts a"
        " join work.tasks t on t.id = a.task_id"
        " join work.instances i on i.id = t.instance_id"
        " where a.id = %s and i.org_id = %s"
        " for update of a, t",
        (attempt_id, org_id),
    )
    row = await cur.fetchone()
    if row is None:
        raise WorkerFenceError("not_found", 404, "Attempt not found", f"No attempt {attempt_id!r}.")
    (
        _aid,
        a_state,
        a_worker,
        a_token,
        task_id,
        attempt_n,
        turn_id,
        reserved_usd,
        usage,
        task_token,
        instance_id,
        kind,
        contract_json,
        task_state,
        attempts_used,
        max_attempts,
        row_org,
        seat,
        seat_version,
        correlation_id,
    ) = row
    current = int(task_token)
    usage_doc = usage if isinstance(usage, dict) else {}
    contract = contract_json if isinstance(contract_json, dict) else {}
    ok = (
        a_state == "CLAIMED"
        and a_worker == worker_id
        and fencing_token == current
        and int(a_token) == current
    )
    if not ok:
        return await write_attempt_fenced(
            conn,
            org_id=row_org,
            instance_id=instance_id,
            task_id=task_id,
            attempt_id=attempt_id,
            correlation_id=correlation_id,
            worker_id=worker_id,
            proposed_token=fencing_token,
            current_token=current,
        )
    return ClaimedAttempt(
        attempt_id=attempt_id,
        task_id=task_id,
        instance_id=instance_id,
        org_id=row_org,
        seat=seat,
        seat_version=int(seat_version),
        correlation_id=correlation_id,
        fencing_token=current,
        attempt_n=int(attempt_n),
        turn_id=turn_id,
        kind=kind,
        contract=contract,
        reserved_usd=float(reserved_usd),
        usage=usage_doc,
        worker_id=worker_id,
        task_state=task_state,
        attempts_used=int(attempts_used),
        max_attempts=int(max_attempts),
    )
