"""Pack-declared domain events and parallel region lifecycle (M2-BE-02)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

if TYPE_CHECKING:
    from .org import OrgModel

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from aos.registry.expressions import ExpressionScope, evaluate
from aos.registry.kinds import TaskTemplate, WorkflowDefinition, WorkflowEventTrigger

from . import ids
from . import workflow
from .outbox import ExecutionEventWrite, write_execution_event


class WorkflowEventError(Exception):
    """A domain event could not be raised."""


async def _load_instance_workflow(
    conn: AsyncConnection, instance_id: str
) -> tuple[
    str,
    str,
    str,
    str,
    int,
    str,
    int,
    str,
    dict[str, Any],
    list[str],
    WorkflowDefinition,
    dict[str, dict[str, dict]],
    str,
    int,
    str,
]:
    cur = await conn.execute(
        "select org_id, workflow, pack_version_id, seat, seat_version, state, version, status,"
        " attributes, correlation_id, raised_events"
        " from work.instances where id = %s for update",
        (instance_id,),
    )
    row = await cur.fetchone()
    if row is None:
        raise WorkflowEventError(f"instance {instance_id!r} not found")
    (
        org_id,
        workflow_name,
        pack_version_id,
        seat_name,
        seat_version,
        _state,
        version,
        inst_status,
        attributes_raw,
        correlation_id,
        raised_raw,
    ) = row
    attributes = attributes_raw if isinstance(attributes_raw, dict) else json.loads(attributes_raw or "{}")
    raised = raised_raw if isinstance(raised_raw, list) else json.loads(raised_raw or "[]")
    raised_events = [str(x) for x in raised]

    pack_cur = await conn.execute(
        "select pack_name, version, digest from registry.pack_versions where id = %s",
        (str(pack_version_id),),
    )
    pack_row = await pack_cur.fetchone()
    if pack_row is None:
        raise WorkflowEventError(f"pack version {pack_version_id!r} not found")
    pack_name, pack_ver, pack_digest = pack_row[0], int(pack_row[1]), pack_row[2]
    graph_revision = f"{pack_name}@{pack_ver}"

    defs = await workflow._load_definitions(conn, str(pack_version_id))
    wdoc = defs.get("WorkflowDefinition", {}).get(workflow_name)
    if wdoc is None:
        raise WorkflowEventError(f"workflow {workflow_name!r} missing on pinned pack")
    definition = WorkflowDefinition.model_validate(wdoc)
    seat_doc = defs.get("Seat", {}).get(seat_name) or {}
    return (
        org_id,
        workflow_name,
        str(pack_version_id),
        seat_name,
        int(seat_version),
        inst_status,
        int(version),
        correlation_id,
        attributes,
        raised_events,
        definition,
        defs,
        pack_name,
        pack_ver,
        pack_digest,
        graph_revision,
        seat_doc,
    )


def _trigger_label(spec: WorkflowEventTrigger) -> str:
    if spec.on_artifact is not None:
        return f"on_artifact:{spec.on_artifact}"
    assert spec.on_attributes is not None
    return "on_attributes:" + ",".join(spec.on_attributes)


async def _start_parallel_region(
    conn: AsyncConnection,
    *,
    packs_dir: Path,
    org_id: str,
    instance_id: str,
    seat_name: str,
    seat_version: int,
    workflow_name: str,
    pack_name: str,
    pack_version: int,
    pack_digest: str,
    defs: dict[str, dict[str, dict]],
    seat_doc: dict[str, Any],
    seat_limits: dict[str, Any],
    participants: list[tuple[str, str]],
    region_on: str,
    definition: WorkflowDefinition,
    org: OrgModel,
) -> None:
    for region in definition.spec.parallel:
        if region.on != region_on:
            continue
        cur = await conn.execute(
            "select 1 from work.regions where instance_id = %s and name = %s",
            (instance_id, region.region),
        )
        if await cur.fetchone() is not None:
            continue
        await conn.execute(
            "insert into work.regions ("
            " instance_id, name, state, started_on, join_at, join_guard, started_with"
            ") values (%s, %s, 'running', %s, %s, %s, '{}'::jsonb)",
            (instance_id, region.region, region.on, region.join_at, region.join_guard),
        )
        tpl = TaskTemplate.model_validate(region.start.model_dump(by_alias=True))
        from . import regions as region_ops

        await region_ops.create_region_task(
            conn,
            packs_dir=packs_dir,
            org_id=org_id,
            instance_id=instance_id,
            seat_name=seat_name,
            seat_version=seat_version,
            workflow_name=workflow_name,
            pack_name=pack_name,
            pack_version=pack_version,
            pack_digest=pack_digest,
            defs=defs,
            seat_doc=seat_doc,
            seat_limits=seat_limits,
            tpl=tpl,
            region_name=region.region,
            participants=participants,
            org=org,
        )


async def raise_event(
    conn: AsyncConnection,
    org: OrgModel,
    instance_id: str,
    name: str,
    *,
    packs_dir: Path,
    trigger: str,
    cause: UUID | None = None,
) -> bool:
    """Raise a declared domain event. Returns True if the event fired; False if skipped (once, or not running)."""
    (
        org_id,
        _workflow_name,
        _pack_version_id,
        seat_name,
        seat_version,
        inst_status,
        _version,
        correlation_id,
        _attributes,
        raised_events,
        definition,
        defs,
        pack_name,
        pack_ver,
        pack_digest,
        graph_revision,
        seat_doc,
    ) = await _load_instance_workflow(conn, instance_id)

    if name not in definition.spec.events:
        raise WorkflowEventError(f"event {name!r} is not declared in spec.events")

    spec = definition.spec.events[name]
    if inst_status != "running":
        return False
    if spec.once and name in raised_events:
        return False

    if spec.once:
        raised_events = [*raised_events, name]
        await conn.execute(
            "update work.instances set raised_events = %s where id = %s",
            (Jsonb(raised_events), instance_id),
        )

    await write_execution_event(
        conn,
        ExecutionEventWrite(
            org_id=org_id,
            run_id=instance_id,
            event_type="WorkflowEventRaised",
            actor_kind="kernel",
            actor_id="kernel",
            correlation_id=correlation_id,
            causation_id=cause,
            redacted_summary=f"Raised event {name}.",
            graph_revision=graph_revision,
            attributes={"event": name, "trigger": trigger},
        ),
    )

    participants = await workflow._participants(conn, instance_id)
    seat_limits = (seat_doc.get("spec") or {}).get("limits") or {}
    event_full = f"event.{name}"
    await _start_parallel_region(
        conn,
        packs_dir=packs_dir,
        org_id=org_id,
        instance_id=instance_id,
        seat_name=seat_name,
        seat_version=seat_version,
        workflow_name=_workflow_name,
        pack_name=pack_name,
        pack_version=pack_ver,
        pack_digest=pack_digest,
        defs=defs,
        seat_doc=seat_doc,
        seat_limits=seat_limits,
        participants=participants,
        region_on=event_full,
        definition=definition,
        org=org,
    )

    await workflow.apply_event(
        conn,
        instance_id,
        event_full,
        by_role=None,
        packs_dir=packs_dir,
        org=org,
        actor={"kind": "kernel", "id": "kernel"},
    )
    return True


def _artifact_scope(content: dict[str, Any], attributes: dict[str, Any]) -> ExpressionScope:
    return {"artifact": dict(content), "attr": dict(attributes)}


def _attribute_scope(attributes: dict[str, Any]) -> ExpressionScope:
    return {"attr": dict(attributes)}


async def evaluate_artifact_triggers(
    conn: AsyncConnection,
    org: OrgModel,
    instance_id: str,
    *,
    artifact_type: str,
    content: dict[str, Any],
    packs_dir: Path,
    cause: UUID | None = None,
) -> None:
    (
        _org_id,
        _wf,
        _pv,
        _seat,
        _sv,
        inst_status,
        _ver,
        _corr,
        attributes,
        _raised,
        definition,
        _defs,
        _pn,
        _pver,
        _pd,
        _gr,
        _sd,
    ) = await _load_instance_workflow(conn, instance_id)
    if inst_status != "running":
        return
    scope = _artifact_scope(content, attributes)
    for ename, etrig in definition.spec.events.items():
        if etrig.on_artifact != artifact_type:
            continue
        if evaluate(etrig.when, scope):
            await raise_event(
                conn,
                org,
                instance_id,
                ename,
                packs_dir=packs_dir,
                trigger=_trigger_label(etrig),
                cause=cause,
            )


async def evaluate_attribute_triggers(
    conn: AsyncConnection,
    org: OrgModel,
    instance_id: str,
    *,
    changed: set[str],
    packs_dir: Path,
    cause: UUID | None = None,
) -> None:
    if not changed:
        return
    (
        _org_id,
        _wf,
        _pv,
        _seat,
        _sv,
        inst_status,
        _ver,
        _corr,
        attributes,
        _raised,
        definition,
        _defs,
        _pn,
        _pver,
        _pd,
        _gr,
        _sd,
    ) = await _load_instance_workflow(conn, instance_id)
    if inst_status != "running":
        return
    scope = _attribute_scope(attributes)
    for ename, etrig in definition.spec.events.items():
        if etrig.on_attributes is None:
            continue
        if not changed.intersection(etrig.on_attributes):
            continue
        if evaluate(etrig.when, scope):
            await raise_event(
                conn,
                org,
                instance_id,
                ename,
                packs_dir=packs_dir,
                trigger=_trigger_label(etrig),
                cause=cause,
            )


async def raise_inbound_event(
    conn: AsyncConnection,
    org: OrgModel,
    instance_id: str,
    event: str,
    *,
    packs_dir: Path,
    inbound_payload: dict[str, Any] | None = None,
) -> bool:
    """Create the current state's on_event Task for *event*, or record WorkflowEventIgnored."""
    actor_kind, actor_id = "kernel", "kernel"
    (
        org_id,
        workflow_name,
        pack_version_id,
        seat_name,
        seat_version,
        inst_status,
        _version,
        correlation_id,
        _attributes,
        _raised,
        definition,
        defs,
        pack_name,
        pack_ver,
        pack_digest,
        graph_revision,
        seat_doc,
    ) = await _load_instance_workflow(conn, instance_id)
    icur = await conn.execute("select state from work.instances where id = %s", (instance_id,))
    inst_row = await icur.fetchone()
    instance_state = str(inst_row[0]) if inst_row else ""

    if inst_status != "running":
        await write_execution_event(
            conn,
            ExecutionEventWrite(
                org_id=org_id,
                run_id=instance_id,
                event_type="WorkflowEventIgnored",
                actor_kind=actor_kind,
                actor_id=actor_id,
                correlation_id=correlation_id,
                redacted_summary=f"Event {event} ignored (not_running) in {instance_state}",
                graph_revision=graph_revision,
                attributes={"state": instance_state, "event": event, "reason": "not_running"},
            ),
        )
        return False

    state_spec = definition.spec.states.get(instance_state)
    if state_spec is None or event not in state_spec.on_event:
        await write_execution_event(
            conn,
            ExecutionEventWrite(
                org_id=org_id,
                run_id=instance_id,
                event_type="WorkflowEventIgnored",
                actor_kind=actor_kind,
                actor_id=actor_id,
                correlation_id=correlation_id,
                redacted_summary=f"Event {event} ignored (no_match) in {instance_state}",
                graph_revision=graph_revision,
                attributes={"state": instance_state, "event": event, "reason": "no_match"},
            ),
        )
        return False

    tpl = state_spec.on_event[event]
    participants = await workflow._participants(conn, instance_id)
    seat_limits = (seat_doc.get("spec") or {}).get("limits") or {}
    trigger_context: dict[str, Any] | None = None
    if inbound_payload:
        from . import inbound_mail

        trigger_context = inbound_mail.trigger_context_from_payload(event=event, payload=inbound_payload)
    await workflow._create_entry_tasks(
        conn,
        packs_dir=packs_dir,
        org_id=org_id,
        instance_id=instance_id,
        seat_name=seat_name,
        seat_version=int(seat_version),
        workflow_name=workflow_name,
        pack_name=pack_name,
        pack_version=pack_ver,
        pack_digest=pack_digest,
        defs=defs,
        seat_doc=seat_doc,
        seat_limits=seat_limits,
        entry_tasks=[tpl],
        participants=participants,
        org=org,
        trigger_context=trigger_context,
    )
    return True


async def on_workflow_task_completed(
    conn: AsyncConnection,
    org: OrgModel,
    *,
    instance_id: str,
    task_id: str,
    packs_dir: Path,
) -> None:
    cur = await conn.execute(
        "select region, template from work.tasks where id = %s and instance_id = %s",
        (task_id, instance_id),
    )
    row = await cur.fetchone()
    if row is None:
        return
    region_name, template = row[0], str(row[1])
    if not region_name:
        moved = await workflow.apply_event(
            conn,
            instance_id,
            f"task.completed.{template}",
            by_role=None,
            packs_dir=packs_dir,
            org=org,
            actor={"kind": "kernel", "id": "kernel"},
        )
        if not moved.applied:
            # No transition on this Task: a decision of the current state may have been waiting for it.
            from . import decisions as decision_ops

            await decision_ops.open_ready_decisions(conn, instance_id, org=org, packs_dir=packs_dir)
        return

    region_name = str(region_name)
    from . import regions as region_ops

    # Lock the instance first, then decide: a re-run committed by another transaction (which holds this lock
    # while it creates the new Task) must be visible before we ask whether this Task is still the latest.
    inst_cur = await conn.execute(
        "select org_id, workflow, pack_version_id, seat, seat_version, state, attributes"
        " from work.instances where id = %s for update",
        (instance_id,),
    )
    inst = await inst_cur.fetchone()
    if inst is None:
        return
    if not await region_ops.is_latest_region_task(
        conn, instance_id=instance_id, region=region_name, task_id=task_id
    ):
        return
    (
        org_id,
        workflow_name,
        pack_version_id,
        seat_name,
        seat_version,
        instance_state,
        attributes_raw,
    ) = inst
    attributes = attributes_raw if isinstance(attributes_raw, dict) else json.loads(attributes_raw or "{}")

    await conn.execute(
        "update work.regions set state = 'done' where instance_id = %s and name = %s and state = 'running'",
        (instance_id, region_name),
    )

    pack_cur = await conn.execute(
        "select pack_name, version, digest from registry.pack_versions where id = %s",
        (str(pack_version_id),),
    )
    pack_row = await pack_cur.fetchone()
    if pack_row is None:
        return
    pack_name, pack_ver, pack_digest = pack_row[0], int(pack_row[1]), pack_row[2]
    defs = await workflow._load_definitions(conn, str(pack_version_id))
    wdoc = defs.get("WorkflowDefinition", {}).get(workflow_name)
    if wdoc is None:
        return
    definition = WorkflowDefinition.model_validate(wdoc)
    seat_doc = defs.get("Seat", {}).get(seat_name) or {}
    seat_limits = (seat_doc.get("spec") or {}).get("limits") or {}
    participants = await workflow._participants(conn, instance_id)

    join_at = next(
        (r.join_at for r in definition.spec.parallel if r.region == region_name),
        None,
    )
    if join_at is not None and instance_state == join_at:
        await region_ops.rerun_stale_regions(
            conn,
            instance_id,
            join_at,
            definition,
            attributes,
            packs_dir=packs_dir,
            org_id=str(org_id),
            seat_name=seat_name,
            seat_version=int(seat_version),
            workflow_name=workflow_name,
            pack_name=pack_name,
            pack_version=pack_ver,
            pack_digest=pack_digest,
            defs=defs,
            seat_doc=seat_doc,
            seat_limits=seat_limits,
            participants=participants,
            org=org,
        )

    from . import decisions as decision_ops

    await decision_ops.open_ready_decisions(conn, instance_id, org=org, packs_dir=packs_dir)
