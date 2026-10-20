"""Scheduler readiness tick: admit CREATED/READY workflow Tasks (M2-BE-05)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from psycopg import AsyncConnection, errors as pg_errors
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from aos.registry.kinds import WorkflowDefinition

from . import ids
from .admission import (
    AdmissionContext,
    check_admission,
    count_live_seat_attempts,
    evaluate_admission,
    task_has_live_attempt,
)
from .instances import _load_definitions, _pack_meta, _refusal_from_admit_backstop, _seat_limits
from .org import OrgModel
from . import tasks as task_ops
from .task_retry import (
    cancel_stale_task,
    immutable_inputs_exist,
    workflow_task_is_admittable,
    workflow_task_is_stale,
)

log = logging.getLogger("aos.readiness")

ReadinessOutcome = Literal["admitted", "waiting", "cancelled", "skipped", "unchanged"]


@dataclass(frozen=True)
class ReadinessResult:
    task_id: str
    outcome: ReadinessOutcome


async def candidate_task_ids(conn: AsyncConnection) -> list[str]:
    cur = await conn.execute(
        "select t.id from work.tasks t"
        " join work.instances i on i.id = t.instance_id"
        " where t.kind = 'task' and t.state in ('CREATED', 'READY') and i.status = 'running'"
        " order by t.created_at, t.id",
    )
    return [str(r[0]) for r in await cur.fetchall()]


def _waiting_for_code(raw: object) -> str | None:
    if not isinstance(raw, dict):
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError:
                return None
        else:
            return None
    if raw.get("kind") != "admission":
        return None
    code = raw.get("code")
    return str(code) if code is not None else None


async def process_ready_task(
    conn: AsyncConnection,
    task_id: str,
    *,
    org: OrgModel,
    packs_dir: Path,
) -> ReadinessResult:
    cur = await conn.execute(
        "select instance_id from work.tasks where id = %s",
        (task_id,),
    )
    row = await cur.fetchone()
    if row is None:
        return ReadinessResult(task_id, "skipped")
    instance_id = str(row[0])

    await conn.execute(
        "select id from work.instances where id = %s for update",
        (instance_id,),
    )
    cur = await conn.execute(
        "select id, instance_id, template, region, state, contract, attempts_used, max_attempts, waiting_for"
        " from work.tasks where id = %s for update skip locked",
        (task_id,),
    )
    trow = await cur.fetchone()
    if trow is None:
        return ReadinessResult(task_id, "skipped")
    (
        _tid,
        _inst_id,
        template,
        region,
        task_state,
        contract_json,
        attempts_used,
        max_attempts,
        waiting_for_raw,
    ) = trow
    if task_state not in ("CREATED", "READY"):
        return ReadinessResult(task_id, "unchanged")

    icur = await conn.execute(
        "select org_id, workflow, pack_version_id, seat, seat_version, state, status, attributes,"
        " correlation_id from work.instances where id = %s",
        (instance_id,),
    )
    inst = await icur.fetchone()
    if inst is None or inst[6] != "running":
        return ReadinessResult(task_id, "unchanged")
    (
        org_id,
        workflow_name,
        pack_version_id,
        seat_name,
        seat_version,
        instance_state,
        _inst_status,
        attributes_raw,
        correlation_id,
    ) = inst
    attributes = attributes_raw if isinstance(attributes_raw, dict) else json.loads(attributes_raw or "{}")

    wcur = await conn.execute(
        "select spec from registry.definitions where pack_version_id = %s and kind = 'WorkflowDefinition'"
        " and name = %s",
        (str(pack_version_id), workflow_name),
    )
    wrow = await wcur.fetchone()
    if wrow is None:
        return ReadinessResult(task_id, "skipped")
    definition = WorkflowDefinition.model_validate(
        wrow[0] if isinstance(wrow[0], dict) else json.loads(wrow[0])
    )

    contract = contract_json if isinstance(contract_json, dict) else json.loads(contract_json)
    region_name = str(region) if region else None
    if await workflow_task_is_stale(
        conn,
        instance_id=instance_id,
        template=str(template),
        region=region_name,
        instance_state=str(instance_state),
        instance_status="running",
        definition=definition,
    ):
        await cancel_stale_task(
            conn,
            org_id=str(org_id),
            instance_id=instance_id,
            task_id=task_id,
            template=str(template),
            from_state=str(instance_state),
            correlation_id=str(correlation_id),
        )
        return ReadinessResult(task_id, "cancelled")

    if not await workflow_task_is_admittable(
        conn,
        task_id=task_id,
        instance_id=instance_id,
        template=str(template),
        region=region_name,
        instance_state=str(instance_state),
        instance_status="running",
        definition=definition,
    ):
        return ReadinessResult(task_id, "unchanged")

    if not await immutable_inputs_exist(conn, instance_id, contract):
        return ReadinessResult(task_id, "unchanged")

    scur = await conn.execute(
        "select state from registry.seats"
        " where org_id = %s and name = %s and version = %s for update",
        (org_id, seat_name, seat_version),
    )
    seat_row = await scur.fetchone()
    if seat_row is None:
        return ReadinessResult(task_id, "unchanged")
    seat_state = seat_row[0]

    if task_state == "CREATED":
        await conn.execute(
            "update work.tasks set state = 'READY', updated_at = now() where id = %s",
            (task_id,),
        )
        from .worker_attempts import emit_task_state_changed

        await emit_task_state_changed(
            conn,
            instance_id=instance_id,
            task_id=task_id,
            template=str(template),
            from_state="CREATED",
            to_state="READY",
        )
        task_state = "READY"

    pack_name, _, _, pack_status = await _pack_meta(conn, str(org_id), str(pack_version_id))
    has_live = await task_has_live_attempt(conn, task_id)
    live_seat = await count_live_seat_attempts(conn, str(org_id), str(seat_name))
    reservation = float((contract.get("budget") or {}).get("cost_usd", 0.0))
    ctx = AdmissionContext(
        org_id=str(org_id),
        actor="scheduler",
        actor_roles=["kernel"],
        seat_name=str(seat_name),
        seat_state=seat_state,
        workflow_name=str(workflow_name),
        instance_id=instance_id,
        pack_version_id=str(pack_version_id),
        pack_published=pack_status == "published",
        task_id=task_id,
        attempts_used=int(attempts_used),
        max_attempts=int(max_attempts),
        has_live_attempt=has_live,
        dependency_versions=attributes,
        contract_dependency_versions=contract.get("dependency_versions") or {},
        reservation_usd=reservation,
        participant_ok=True,
        live_seat_attempts=live_seat,
    )

    existing_code = _waiting_for_code(waiting_for_raw)
    fail = await evaluate_admission(conn, ctx)
    if fail is not None:
        await conn.execute(
            "update work.tasks set state = 'READY', waiting_for = %s, updated_at = now() where id = %s",
            (Jsonb({"kind": "admission", "code": fail.code}), task_id),
        )
        if existing_code != fail.code:
            await check_admission(conn, ctx, record_denial=True)
        return ReadinessResult(task_id, "waiting")

    defs = await _load_definitions(conn, str(pack_version_id))
    seat_doc = defs.get("Seat", {}).get(seat_name) or {}
    daily_limit = float(_seat_limits(seat_doc)["daily_cost_usd"])
    new_attempt_id = ids.new_attempt_id()
    attempt_n = int(attempts_used) + 1
    try:
        async with conn.transaction():
            await task_ops.admit_attempt(
                conn,
                org_id=str(org_id),
                seat=str(seat_name),
                daily_limit_usd=daily_limit,
                task_id=task_id,
                attempt_id=new_attempt_id,
                turn_id=None,
                attempt_n=attempt_n,
                reservation_usd=reservation,
            )
    except (pg_errors.CheckViolation, pg_errors.UniqueViolation) as exc:
        # The backstop records the refusal itself; don't write a second record here.
        refusal = await _refusal_from_admit_backstop(conn, ctx, exc)
        if refusal:
            await conn.execute(
                "update work.tasks set state = 'READY', waiting_for = %s, updated_at = now() where id = %s",
                (Jsonb({"kind": "admission", "code": refusal.code}), task_id),
            )
            return ReadinessResult(task_id, "waiting")
        raise

    await conn.execute(
        "update work.tasks set waiting_for = null, updated_at = now() where id = %s",
        (task_id,),
    )
    return ReadinessResult(task_id, "admitted")


async def run_readiness_tick(
    pool: AsyncConnectionPool,
    *,
    org: OrgModel,
    packs_dir: Path,
) -> list[ReadinessResult]:
    async with pool.connection() as conn:
        candidates = await candidate_task_ids(conn)
    results: list[ReadinessResult] = []
    for task_id in candidates:
        try:
            async with pool.connection() as conn:
                async with conn.transaction():
                    result = await process_ready_task(
                        conn, task_id, org=org, packs_dir=packs_dir
                    )
            results.append(result)
        except Exception:  # noqa: BLE001
            log.exception("readiness task %s failed", task_id)
    return results
