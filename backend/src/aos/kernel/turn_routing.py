"""Route participant turns to workflow Task resume/revise or assist (M2-AG-01)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from psycopg import AsyncConnection

from aos.registry.kinds import TaskTemplate, WorkflowDefinition

from . import decisions, tasks as task_ops, workflow
from .org import OrgModel


RouteKind = Literal["resume", "revise", "assist"]


@dataclass(frozen=True)
class TurnRoute:
    kind: RouteKind
    task_id: str
    template: str | None
    contract: dict[str, Any]
    attempts_used: int
    max_attempts: int
    task_state_before: str


async def _open_decision_waiting_on_writer(
    conn: AsyncConnection,
    *,
    instance_id: str,
    person_id: str,
    roles: list[str],
) -> bool:
    cur = await conn.execute(
        "select 1 from work.pending_items"
        " where instance_id = %s and status = 'open' and kind = 'decision'"
        " and (for_person_id = %s or for_role = any(%s::text[]))"
        " limit 1",
        (instance_id, person_id, roles),
    )
    return await cur.fetchone() is not None


async def _latest_task_for_writer_roles(
    conn: AsyncConnection,
    *,
    instance_id: str,
    definition: WorkflowDefinition,
    instance_state: str,
    writer_roles: list[str],
) -> task_ops.TaskRow | None:
    state_spec = definition.spec.states.get(instance_state)
    if state_spec is None:
        return None
    templates = [t.template for t in state_spec.tasks]
    latest = await task_ops.latest_task_rows_for_templates(conn, instance_id, templates)
    candidates: list[task_ops.TaskRow] = []
    for row in latest.values():
        role = (row.contract.get("on_behalf_of") or {}).get("role")
        if role and str(role) in writer_roles:
            candidates.append(row)
    if not candidates:
        return None
    return max(candidates, key=lambda r: (r.created_at, r.task_id))


async def resolve_turn_route(
    conn: AsyncConnection,
    *,
    instance_id: str,
    instance_state: str,
    workflow_name: str,
    pack_version_id: str,
    writer_id: str,
    writer_roles: list[str],
) -> TurnRoute | None:
    """Workflow Task route for this writer, or None to use assist."""
    wcur = await conn.execute(
        "select spec from registry.definitions where pack_version_id = %s and kind = 'WorkflowDefinition'"
        " and name = %s",
        (pack_version_id, workflow_name),
    )
    wrow = await wcur.fetchone()
    if wrow is None:
        return None
    definition = WorkflowDefinition.model_validate(
        wrow[0] if isinstance(wrow[0], dict) else json.loads(wrow[0])
    )
    row = await _latest_task_for_writer_roles(
        conn,
        instance_id=instance_id,
        definition=definition,
        instance_state=str(instance_state),
        writer_roles=writer_roles,
    )
    if row is None:
        return None
    if row.state == "WAITING_INPUT":
        return TurnRoute(
            kind="resume",
            task_id=row.task_id,
            template=row.template,
            contract=row.contract,
            attempts_used=row.attempts_used,
            max_attempts=row.max_attempts,
            task_state_before=row.state,
        )
    if row.state == "COMPLETED" and await _open_decision_waiting_on_writer(
        conn, instance_id=instance_id, person_id=writer_id, roles=writer_roles
    ):
        return TurnRoute(
            kind="revise",
            task_id=row.task_id,
            template=row.template,
            contract=row.contract,
            attempts_used=0,
            max_attempts=row.max_attempts,
            task_state_before=row.state,
        )
    return None


async def create_revise_replacement_task(
    conn: AsyncConnection,
    *,
    org: OrgModel,
    org_id: str,
    instance_id: str,
    seat_name: str,
    seat_version: int,
    workflow_name: str,
    packs_dir: Path,
    pack_version_id: str,
    superseded_task_id: str,
    template: str,
    voided_by: str,
) -> str:
    """New Task for the same template; voids view decisions; marks the old Task superseded."""
    from .instances import _load_definitions, _pack_meta, _seat_limits

    pack_name, pack_ver, pack_digest, _ = await _pack_meta(conn, org_id, pack_version_id)
    defs = await _load_definitions(conn, pack_version_id)
    wdoc = defs.get("WorkflowDefinition", {}).get(workflow_name) or {}
    definition = WorkflowDefinition.model_validate(wdoc)
    state = (
        await conn.execute("select state from work.instances where id = %s", (instance_id,))
    )
    inst_state = (await state.fetchone() or (None,))[0]
    state_spec = definition.spec.states.get(str(inst_state))
    if state_spec is None:
        raise RuntimeError("instance state missing from workflow")
    entry = next((t for t in state_spec.tasks if t.template == template), None)
    if entry is None:
        raise RuntimeError(f"template {template!r} not in current state")
    seat_doc = defs.get("Seat", {}).get(seat_name) or {}
    seat_limits = _seat_limits(seat_doc)
    participants = await workflow._participants(conn, instance_id)
    if state_spec.view:
        await decisions.void_open_decisions_for_state_view(
            conn,
            instance_id=instance_id,
            view_type=str(state_spec.view),
            voided_by=voided_by,
        )
    before = await conn.execute(
        "select id from work.tasks where instance_id = %s and template = %s and region is null"
        " and superseded_by is null order by created_at desc, id desc limit 1",
        (instance_id, template),
    )
    old_id = (await before.fetchone() or (superseded_task_id,))[0]
    await workflow._create_entry_tasks(
        conn,
        packs_dir=packs_dir,
        org_id=org_id,
        instance_id=instance_id,
        seat_name=seat_name,
        seat_version=seat_version,
        workflow_name=workflow_name,
        pack_name=pack_name,
        pack_version=pack_ver,
        pack_digest=pack_digest,
        defs=defs,
        seat_doc=seat_doc,
        seat_limits=seat_limits,
        entry_tasks=[entry],
        participants=participants,
        org=org,
    )
    after = await conn.execute(
        "select id from work.tasks where instance_id = %s and template = %s and region is null"
        " and superseded_by is null order by created_at desc, id desc limit 1",
        (instance_id, template),
    )
    new_row = await after.fetchone()
    if new_row is None:
        raise RuntimeError("revise could not create replacement task")
    new_id = str(new_row[0])
    await task_ops.mark_superseded(conn, old_task_id=str(old_id), new_task_id=new_id)
    return new_id


def workflow_entry_templates(wdoc: dict[str, Any], state_name: str) -> list[TaskTemplate]:
    spec = (wdoc.get("spec") or {}).get("states") or {}
    state = spec.get(state_name) or {}
    raw_tasks = state.get("tasks") or []
    return [TaskTemplate.model_validate(t) for t in raw_tasks]


async def workflow_task_running_for_writer(
    conn: AsyncConnection,
    *,
    instance_id: str,
    workflow_name: str,
    pack_version_id: str,
    instance_state: str,
    writer_roles: list[str],
) -> bool:
    wcur = await conn.execute(
        "select spec from registry.definitions where pack_version_id = %s and kind = 'WorkflowDefinition'"
        " and name = %s",
        (pack_version_id, workflow_name),
    )
    wrow = await wcur.fetchone()
    if wrow is None:
        return False
    definition = WorkflowDefinition.model_validate(
        wrow[0] if isinstance(wrow[0], dict) else json.loads(wrow[0])
    )
    row = await _latest_task_for_writer_roles(
        conn,
        instance_id=instance_id,
        definition=definition,
        instance_state=instance_state,
        writer_roles=writer_roles,
    )
    return row is not None and row.state == "RUNNING"


async def intake_task_for_start(
    conn: AsyncConnection,
    instance_id: str,
    *,
    wdoc: dict[str, Any],
    initial_state: str,
    requester_role: str,
) -> task_ops.TaskRow | None:
    templates = [t.template for t in workflow_entry_templates(wdoc, str(initial_state))]
    latest = await task_ops.latest_task_rows_for_templates(conn, instance_id, templates)
    candidates = [
        r
        for r in latest.values()
        if str((r.contract.get("on_behalf_of") or {}).get("role")) == requester_role
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda r: (r.created_at, r.task_id))
