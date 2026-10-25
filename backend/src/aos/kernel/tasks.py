"""Task and attempt persistence for admission (M1)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from . import ids
from .admission import reserve_budget


@dataclass(frozen=True)
class TaskRow:
    task_id: str
    template: str
    state: str
    contract: dict[str, Any]
    attempts_used: int
    max_attempts: int
    region: str | None
    created_at: Any


async def latest_task_rows_for_templates(
    conn: AsyncConnection,
    instance_id: str,
    templates: list[str],
    *,
    region: str | None = None,
) -> dict[str, TaskRow]:
    """Latest non-superseded Task per template (created_at, then id)."""
    if not templates:
        return {}
    if region is None:
        cur = await conn.execute(
            "select distinct on (template)"
            " id, template, state, contract, attempts_used, max_attempts, region, created_at"
            " from work.tasks"
            " where instance_id = %s and template = any(%s) and kind = 'task'"
            " and region is null and superseded_by is null"
            " order by template, created_at desc, id desc",
            (instance_id, templates),
        )
    else:
        cur = await conn.execute(
            "select distinct on (template)"
            " id, template, state, contract, attempts_used, max_attempts, region, created_at"
            " from work.tasks"
            " where instance_id = %s and template = any(%s) and kind = 'task'"
            " and region = %s and superseded_by is null"
            " order by template, created_at desc, id desc",
            (instance_id, templates, region),
        )
    out: dict[str, TaskRow] = {}
    for row in await cur.fetchall():
        tid, tpl, state, contract_json, used, max_a, reg, created_at = row
        contract = contract_json if isinstance(contract_json, dict) else json.loads(contract_json)
        out[str(tpl)] = TaskRow(
            task_id=str(tid),
            template=str(tpl),
            state=str(state),
            contract=contract,
            attempts_used=int(used),
            max_attempts=int(max_a),
            region=str(reg) if reg is not None else None,
            created_at=created_at,
        )
    return out


async def mark_superseded(conn: AsyncConnection, *, old_task_id: str, new_task_id: str) -> None:
    await conn.execute(
        "update work.tasks set superseded_by = %s, updated_at = now() where id = %s and superseded_by is null",
        (new_task_id, old_task_id),
    )


async def count_attempts_for_turn(conn: AsyncConnection, task_id: str, turn_id: str) -> int:
    cur = await conn.execute(
        "select count(*) from work.attempts where task_id = %s and turn_id = %s",
        (task_id, turn_id),
    )
    row = await cur.fetchone()
    return int(row[0]) if row else 0


async def update_assist_task_contract(
    conn: AsyncConnection,
    *,
    task_id: str,
    skill: str,
    work_type: str,
    contract: dict[str, Any],
) -> None:
    await conn.execute(
        "update work.tasks set skill = %s, work_type = %s, contract = %s, contract_hash = %s, updated_at = now()"
        " where id = %s",
        (skill, work_type, Jsonb(contract), contract["contract_hash"], task_id),
    )


async def insert_assist_task(
    conn: AsyncConnection,
    *,
    task_id: str,
    instance_id: str,
    skill: str,
    work_type: str,
    contract: dict[str, Any],
    max_attempts: int,
) -> None:
    await conn.execute(
        "insert into work.tasks ("
        " id, instance_id, kind, template, skill, work_type, verifier, state, contract, contract_hash,"
        " max_attempts"
        ") values (%s, %s, 'assist', 'assist', %s, %s, null, 'CREATED', %s, %s, %s)",
        (task_id, instance_id, skill, work_type, Jsonb(contract), contract["contract_hash"], max_attempts),
    )


async def insert_workflow_task(
    conn: AsyncConnection,
    *,
    task_id: str,
    instance_id: str,
    template: str,
    skill: str,
    work_type: str,
    verifier: str | None,
    contract: dict[str, Any],
    max_attempts: int,
    region: str | None = None,
) -> None:
    await conn.execute(
        "insert into work.tasks ("
        " id, instance_id, kind, template, skill, work_type, verifier, region, state, contract, contract_hash,"
        " max_attempts"
        ") values (%s, %s, 'task', %s, %s, %s, %s, %s, 'CREATED', %s, %s, %s)",
        (
            task_id,
            instance_id,
            template,
            skill,
            work_type,
            verifier,
            region,
            Jsonb(contract),
            contract["contract_hash"],
            max_attempts,
        ),
    )


async def admit_attempt(
    conn: AsyncConnection,
    *,
    org_id: str,
    seat: str,
    daily_limit_usd: float,
    task_id: str,
    attempt_id: str,
    turn_id: str | None,
    attempt_n: int,
    reservation_usd: float,
) -> int:
    cur = await conn.execute(
        "select fencing_token, attempts_used from work.tasks where id = %s for update",
        (task_id,),
    )
    row = await cur.fetchone()
    if row is None:
        raise RuntimeError(f"task {task_id!r} missing")
    fencing_token, attempts_used = int(row[0]), int(row[1])
    new_token = fencing_token + 1
    await conn.execute(
        "update work.tasks set fencing_token = %s, attempts_used = %s, state = 'RUNNING', updated_at = now()"
        " where id = %s",
        (new_token, attempts_used + 1, task_id),
    )
    await conn.execute(
        "insert into work.attempts ("
        " id, task_id, n, fencing_token, state, turn_id, reserved_usd"
        ") values (%s, %s, %s, %s, 'ADMITTED', %s, %s)",
        (attempt_id, task_id, attempt_n, new_token, turn_id, reservation_usd),
    )
    await reserve_budget(
        conn,
        org_id=org_id,
        seat=seat,
        daily_limit_usd=daily_limit_usd,
        reservation_usd=reservation_usd,
    )
    from . import regions as region_ops

    await region_ops.record_started_with_on_admit(conn, task_id)
    return new_token
