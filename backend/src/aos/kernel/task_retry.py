"""Workflow Task retry pending items and readiness helpers (M2-BE-05)."""

from __future__ import annotations

import json
from datetime import timezone
from pathlib import Path
from typing import Any

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from aos.registry.kinds import TaskTemplate, WorkflowDefinition

from . import audit_store, clock, ids, workflow
from . import participants as participant_ops
from . import regions as region_ops
from . import tasks as task_ops
from .decisions import DecisionError, _decision_request_hash, _emit_pending_created, _emit_pending_resolved
from .instances import _load_definitions, _pack_meta, _refusal_from_admit_backstop, _seat_limits
from .org import OrgModel
from .outbox import ExecutionEventWrite, write_execution_event
from .progress import _state_label, post_decision_resolved_progress, post_task_outcome_progress
from .worker_attempts import emit_task_state_changed


async def immutable_inputs_exist(
    conn: AsyncConnection, instance_id: str, contract: dict[str, Any]
) -> bool:
    for ref in contract.get("immutable_input_refs") or []:
        if not isinstance(ref, dict):
            return False
        aid = ref.get("artifact_id")
        ver = ref.get("version")
        if not aid or ver is None:
            return False
        cur = await conn.execute(
            "select 1 from work.artifact_versions av"
            " join work.artifacts a on a.id = av.artifact_id"
            " where av.artifact_id = %s and av.version = %s and a.instance_id = %s",
            (str(aid), int(ver), instance_id),
        )
        if await cur.fetchone() is None:
            return False
    return True


def _state_templates(definition: WorkflowDefinition, state: str) -> list[str]:
    spec = definition.spec.states.get(state)
    if spec is None:
        return []
    return [t.template for t in spec.tasks]


def _state_event_templates(definition: WorkflowDefinition, state: str) -> list[str]:
    spec = definition.spec.states.get(state)
    if spec is None or not spec.on_event:
        return []
    return [t.template for t in spec.on_event.values()]


def _state_allowed_templates(definition: WorkflowDefinition, state: str) -> list[str]:
    return _state_templates(definition, state) + _state_event_templates(definition, state)


async def workflow_task_is_stale(
    conn: AsyncConnection,
    *,
    instance_id: str,
    template: str,
    region: str | None,
    instance_state: str,
    instance_status: str,
    definition: WorkflowDefinition,
) -> bool:
    if instance_status != "running":
        return True
    if region:
        cur = await conn.execute(
            "select state from work.regions where instance_id = %s and name = %s",
            (instance_id, region),
        )
        row = await cur.fetchone()
        if row is None:
            return True
        return row[0] in ("joined", "done")
    return template not in _state_allowed_templates(definition, instance_state)


async def workflow_task_is_admittable(
    conn: AsyncConnection,
    *,
    task_id: str,
    instance_id: str,
    template: str,
    region: str | None,
    instance_state: str,
    instance_status: str,
    definition: WorkflowDefinition,
) -> bool:
    if instance_status != "running":
        return False
    if region:
        cur = await conn.execute(
            "select state from work.regions where instance_id = %s and name = %s",
            (instance_id, region),
        )
        row = await cur.fetchone()
        if row is None or row[0] != "running":
            return False
        return await region_ops.is_latest_region_task(
            conn, instance_id=instance_id, region=region, task_id=task_id
        )
    return template in _state_allowed_templates(definition, instance_state)


async def retry_context_valid(
    conn: AsyncConnection,
    *,
    template: str,
    region: str | None,
    instance_id: str,
    instance_state: str,
    instance_status: str,
    definition: WorkflowDefinition,
) -> bool:
    """True when deciding task.retry can still spawn a replacement task."""
    if instance_status != "running":
        return False
    if region:
        cur = await conn.execute(
            "select state from work.regions where instance_id = %s and name = %s",
            (instance_id, region),
        )
        row = await cur.fetchone()
        if row is None:
            return False
        return row[0] == "running"
    return template in _state_templates(definition, instance_state)


async def retry_title_state_name(
    conn: AsyncConnection,
    *,
    pack_version_id: str,
    workflow_name: str,
    definition: WorkflowDefinition,
    template: str,
    region: str | None,
    instance_state: str,
) -> str:
    if region:
        for spec in definition.spec.parallel:
            if spec.region == region:
                return await _state_label(
                    conn,
                    pack_version_id=pack_version_id,
                    workflow_name=workflow_name,
                    state_name=spec.join_at,
                )
    return await _state_label(
        conn,
        pack_version_id=pack_version_id,
        workflow_name=workflow_name,
        state_name=instance_state,
    )


async def cancel_stale_task(
    conn: AsyncConnection,
    *,
    org_id: str,
    instance_id: str,
    task_id: str,
    template: str,
    from_state: str,
    correlation_id: str,
) -> None:
    cur = await conn.execute(
        "select state from work.tasks where id = %s and state in ('CREATED', 'READY') for update",
        (task_id,),
    )
    row = await cur.fetchone()
    if row is None:
        return
    prior_state = str(row[0])
    await conn.execute(
        "update work.tasks set state = 'CANCELLED', updated_at = now() where id = %s",
        (task_id,),
    )
    await emit_task_state_changed(
        conn,
        instance_id=instance_id,
        task_id=task_id,
        template=template,
        from_state=prior_state,
        to_state="CANCELLED",
    )
    await write_execution_event(
        conn,
        ExecutionEventWrite(
            org_id=org_id,
            run_id=instance_id,
            event_type="TaskCancelled",
            actor_kind="kernel",
            actor_id="scheduler",
            correlation_id=correlation_id,
            redacted_summary="Task is no longer current for this job.",
            task_id=task_id,
            attributes={"reason": "not_current", "state": from_state},
        ),
    )


async def void_open_task_retry(
    conn: AsyncConnection,
    *,
    instance_id: str,
    pending_id: str,
    for_person_id: str,
    voided_by: str,
) -> None:
    ts = clock.now()
    await conn.execute(
        "update work.pending_items set status = 'voided', resolved_at = %s, resolved_by = %s"
        " where id = %s and status = 'open'",
        (ts, voided_by, pending_id),
    )
    await _emit_pending_resolved(
        conn,
        instance_id=instance_id,
        person_id=for_person_id,
        pending_id=pending_id,
        outcome="voided",
        by=voided_by,
    )


async def void_task_retry_on_state_leave(
    conn: AsyncConnection,
    *,
    instance_id: str,
    from_state: str,
    definition: WorkflowDefinition,
    job_closed: bool,
) -> None:
    if job_closed:
        cur = await conn.execute(
            "select id, for_person_id from work.pending_items"
            " where instance_id = %s and status = 'open' and event = 'task.retry'",
            (instance_id,),
        )
    else:
        templates = _state_templates(definition, from_state)
        cur = await conn.execute(
            "select p.id, p.for_person_id from work.pending_items p"
            " join work.tasks t on t.id = p.task_id"
            " where p.instance_id = %s and p.status = 'open' and p.event = 'task.retry'"
            " and ((t.region is null and t.template = any(%s))"
            "      or (t.region is not null and exists ("
            "        select 1 from work.regions r"
            "        where r.instance_id = t.instance_id and r.name = t.region and r.join_at = %s)))",
            (instance_id, templates, from_state),
        )
    for pending_id, for_person in await cur.fetchall():
        await void_open_task_retry(
            conn,
            instance_id=instance_id,
            pending_id=str(pending_id),
            for_person_id=str(for_person),
            voided_by="kernel",
        )


async def open_task_retry_pending(
    conn: AsyncConnection,
    *,
    org: OrgModel,
    org_id: str,
    instance_id: str,
    task_id: str,
) -> str | None:
    cur = await conn.execute(
        "select 1 from work.pending_items"
        " where task_id = %s and event = 'task.retry' and status = 'open' limit 1",
        (task_id,),
    )
    if await cur.fetchone() is not None:
        return None

    icur = await conn.execute(
        "select workflow, pack_version_id, state from work.instances where id = %s",
        (instance_id,),
    )
    inst = await icur.fetchone()
    if inst is None:
        return None
    workflow_name, pack_version_id, instance_state = inst[0], str(inst[1]), inst[2]
    tcur = await conn.execute(
        "select template, region, contract from work.tasks where id = %s",
        (task_id,),
    )
    trow = await tcur.fetchone()
    if trow is None:
        return None
    template, region, contract_json = trow[0], trow[1], trow[2]
    contract = contract_json if isinstance(contract_json, dict) else json.loads(contract_json)
    on_behalf = contract.get("on_behalf_of") or {}
    role = on_behalf.get("role")
    if not role:
        return None
    person_id = await participant_ops.resolve_participant(conn, org, instance_id, str(role))
    if person_id is None:
        return None

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
    label = await retry_title_state_name(
        conn,
        pack_version_id=pack_version_id,
        workflow_name=str(workflow_name),
        definition=definition,
        template=str(template),
        region=str(region) if region else None,
        instance_state=str(instance_state),
    )
    title = f"Retry: {label}"
    ts = clock.now()
    pending_id = ids.new_pending_id()
    options = [{"value": "retry", "label": "Retry this step"}]
    pending_doc = {
        "pending_id": pending_id,
        "instance_id": instance_id,
        "kind": "decision",
        "event": "task.retry",
        "title": title,
        "detail": "",
        "for_role": str(role),
        "for_person_id": person_id,
        "options": options,
        "artifact_ref": None,
        "approval_id": None,
        "due_at": None,
        "status": "open",
        "created_at": ts.isoformat(),
    }
    await conn.execute(
        "insert into work.pending_items ("
        " id, instance_id, kind, event, title, detail, for_role, for_person_id,"
        " options, artifact_ref, task_id, status, created_at"
        ") values (%s, %s, 'decision', 'task.retry', %s, '', %s, %s, %s, null, %s, 'open', %s)",
        (
            pending_id,
            instance_id,
            title,
            role,
            person_id,
            Jsonb(options),
            task_id,
            ts,
        ),
    )
    await _emit_pending_created(conn, instance_id=instance_id, person_id=person_id, pending=pending_doc)
    return pending_id


async def finalize_workflow_task_exception(
    conn: AsyncConnection,
    *,
    org: OrgModel,
    org_id: str,
    instance_id: str,
    task_id: str,
    attempt_id: str | None,
    summary: str | None = None,
) -> None:
    await post_task_outcome_progress(
        conn,
        org=org,
        org_id=org_id,
        instance_id=instance_id,
        task_id=task_id,
        summary=summary,
        attempt_id=attempt_id,
    )
    await open_task_retry_pending(
        conn,
        org=org,
        org_id=org_id,
        instance_id=instance_id,
        task_id=task_id,
    )


async def spawn_replacement_task(
    conn: AsyncConnection,
    *,
    packs_dir: Path,
    org: OrgModel,
    org_id: str,
    instance_id: str,
    failed_task_id: str,
    definition: WorkflowDefinition,
    workflow_name: str,
    pack_version_id: str,
    seat_name: str,
    seat_version: int,
) -> str:
    cur = await conn.execute(
        "select template, region from work.tasks where id = %s",
        (failed_task_id,),
    )
    row = await cur.fetchone()
    if row is None:
        raise DecisionError("not_found", 404, "Task not found", "The failed task no longer exists.")
    template, region = str(row[0]), row[1]
    pack_name, pack_ver, pack_digest, _ = await _pack_meta(conn, org_id, pack_version_id)
    defs = await _load_definitions(conn, pack_version_id)
    seat_doc = defs.get("Seat", {}).get(seat_name) or {}
    seat_limits = _seat_limits(seat_doc)
    participants = await workflow._participants(conn, instance_id)

    if region:
        region_name = str(region)
        for spec in definition.spec.parallel:
            if spec.region != region_name:
                continue
            await conn.execute(
                "update work.regions set state = 'running', started_with = '{}'::jsonb"
                " where instance_id = %s and name = %s",
                (instance_id, region_name),
            )
            tpl = TaskTemplate.model_validate(spec.start.model_dump(by_alias=True))
            return await region_ops.create_region_task(
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
                tpl=tpl,
                region_name=region_name,
                participants=participants,
                org=org,
            )
        raise DecisionError("internal", 500, "Region missing", f"No parallel spec for region {region_name!r}.")

    icur = await conn.execute("select state from work.instances where id = %s", (instance_id,))
    inst_state = (await icur.fetchone() or (None,))[0]
    state_spec = definition.spec.states.get(str(inst_state))
    if state_spec is None:
        raise DecisionError("conflict", 409, "Job moved on", "This job is no longer in a state that allows retry.")
    entry = next((t for t in state_spec.tasks if t.template == template), None)
    if entry is None:
        raise DecisionError("conflict", 409, "Job moved on", "This job is no longer in a state that allows retry.")
    before = await conn.execute(
        "select count(*) from work.tasks where instance_id = %s and template = %s and region is null",
        (instance_id, template),
    )
    count_before = int((await before.fetchone())[0])
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
        " order by created_at desc, id desc limit 1",
        (instance_id, template),
    )
    new_row = await after.fetchone()
    if new_row is None or int(count_before) == 0:
        raise DecisionError("internal", 500, "Retry failed", "Could not create a replacement task.")
    return str(new_row[0])


async def decide_task_retry(
    conn: AsyncConnection,
    org: OrgModel,
    org_id: str,
    pending_id: str,
    person_id: str,
    body: dict[str, Any],
    *,
    idempotency_key: str | None,
    packs_dir: Path,
) -> dict[str, Any]:
    req_hash = _decision_request_hash(pending_id, body)
    if idempotency_key:
        cur = await conn.execute(
            "select request_hash, response from gov.decision_records"
            " where org_id = %s and actor = %s and idempotency_key = %s",
            (org_id, person_id, idempotency_key),
        )
        prev = await cur.fetchone()
        if prev is not None:
            stored_hash, response = prev[0], prev[1]
            if stored_hash != req_hash:
                raise DecisionError(
                    "validation_failed",
                    422,
                    "Idempotency key reused",
                    "The same Idempotency-Key was used with a different request body.",
                )
            if isinstance(response, dict):
                return response
            return json.loads(response) if isinstance(response, str) else dict(response)

    # Lock order: the instance row first, then the pending item (apply_event voids retry items after locking
    # the instance, so locking the item first could deadlock with it).
    pre_cur = await conn.execute(
        "select instance_id from work.pending_items where id = %s",
        (pending_id,),
    )
    pre_row = await pre_cur.fetchone()
    if pre_row is None:
        raise DecisionError("not_found", 404, "Pending item not found", f"No pending item {pending_id!r}.")
    await conn.execute("select id from work.instances where id = %s for update", (pre_row[0],))
    pend_cur = await conn.execute(
        "select instance_id, for_person_id, status, task_id from work.pending_items where id = %s for update",
        (pending_id,),
    )
    pend_row = await pend_cur.fetchone()
    if pend_row is None:
        raise DecisionError("not_found", 404, "Pending item not found", f"No pending item {pending_id!r}.")
    instance_id, for_person, pend_status, task_id = pend_row
    if pend_status != "open":
        raise DecisionError(
            "conflict",
            409,
            "Decision already handled",
            "This decision card is no longer open.",
        )
    if for_person != person_id:
        raise DecisionError(
            "not_permitted",
            403,
            "Not your decision",
            "Only the participant this item waits on may answer it.",
        )
    if not task_id:
        raise DecisionError("internal", 500, "Retry card invalid", "This retry card is not bound to a task.")

    inst_cur = await conn.execute(
        "select org_id, workflow, pack_version_id, state, version, status, correlation_id, seat, seat_version"
        " from work.instances where id = %s for update",
        (instance_id,),
    )
    inst = await inst_cur.fetchone()
    if inst is None or inst[0] != org_id:
        raise DecisionError("not_found", 404, "Pending item not found", f"No pending item {pending_id!r}.")
    (
        _inst_org,
        workflow_name,
        pack_version_id,
        from_state,
        inst_version,
        inst_status,
        _correlation_id,
        seat_name,
        seat_version,
    ) = inst

    expected = body.get("expected_version")
    if expected is None or int(expected) != int(inst_version):
        raise DecisionError(
            "stale_version",
            409,
            "Job changed",
            "Reload the job and try again.",
            current_version=int(inst_version),
        )

    value = str(body.get("value") or "retry")
    if value != "retry":
        raise DecisionError("validation_failed", 422, "Invalid choice", "Choose retry to continue.")

    wcur = await conn.execute(
        "select spec from registry.definitions where pack_version_id = %s and kind = 'WorkflowDefinition'"
        " and name = %s",
        (str(pack_version_id), workflow_name),
    )
    wrow = await wcur.fetchone()
    definition = WorkflowDefinition.model_validate(
        wrow[0] if isinstance(wrow[0], dict) else json.loads(wrow[0])
    )
    tcur = await conn.execute(
        "select template, region, state from work.tasks where id = %s",
        (task_id,),
    )
    trow = await tcur.fetchone()
    if trow is None:
        await void_open_task_retry(
            conn,
            instance_id=str(instance_id),
            pending_id=pending_id,
            for_person_id=person_id,
            voided_by="kernel",
        )
        raise DecisionError("conflict", 409, "Task gone", "This task is no longer available to retry.")
    template, region, task_state = str(trow[0]), trow[1], trow[2]
    if task_state != "EXCEPTION":
        raise DecisionError("conflict", 409, "Task not failed", "Only a failed task can be retried.")

    if not await retry_context_valid(
        conn,
        template=template,
        region=str(region) if region else None,
        instance_id=str(instance_id),
        instance_state=str(from_state),
        instance_status=str(inst_status),
        definition=definition,
    ):
        await void_open_task_retry(
            conn,
            instance_id=str(instance_id),
            pending_id=pending_id,
            for_person_id=person_id,
            voided_by="kernel",
        )
        raise DecisionError(
            "conflict",
            409,
            "Too late to retry",
            "The job has moved on; this retry is no longer available.",
        )

    ts = clock.now()
    decision_id = ids.new_decision_id()
    roles = await conn.execute(
        "select role from work.participants where instance_id = %s and person_id = %s",
        (instance_id, person_id),
    )
    actor_roles = [r[0] for r in await roles.fetchall()]
    actor_role = actor_roles[0] if actor_roles else "buyer"

    new_task_id = await spawn_replacement_task(
        conn,
        packs_dir=packs_dir,
        org=org,
        org_id=org_id,
        instance_id=str(instance_id),
        failed_task_id=str(task_id),
        definition=definition,
        workflow_name=str(workflow_name),
        pack_version_id=str(pack_version_id),
        seat_name=str(seat_name),
        seat_version=int(seat_version),
    )

    await conn.execute(
        "update work.pending_items set status = 'resolved', resolved_at = %s, resolved_by = %s where id = %s",
        (ts, person_id, pending_id),
    )
    await _emit_pending_resolved(
        conn,
        instance_id=str(instance_id),
        person_id=person_id,
        pending_id=pending_id,
        outcome="resolved",
        by=person_id,
    )

    from_spec = definition.spec.states.get(from_state) if from_state else None
    unchanged_label = from_spec.label if from_spec is not None else from_state
    await post_decision_resolved_progress(
        conn,
        org=org,
        org_id=org_id,
        instance_id=str(instance_id),
        decider_id=person_id,
        decision_label="Retry",
        job_moved=False,
        state_label_if_unchanged=str(unchanged_label or from_state),
    )

    record_body = {
        "decision_id": decision_id,
        "instance_id": instance_id,
        "event": "task.retry",
        "value": value,
        "actor": person_id,
        "role": actor_role,
        "at": ts.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "artifact_ref": None,
        "resulting_state": from_state,
        "new_task_id": new_task_id,
    }
    await conn.execute(
        "insert into gov.decision_records ("
        " id, org_id, subject_kind, subject_id, event, value, actor, actor_role,"
        " idempotency_key, request_hash, response"
        ") values (%s, %s, 'instance', %s, 'task.retry', %s, %s, %s, %s, %s, %s)",
        (
            decision_id,
            org_id,
            instance_id,
            value,
            person_id,
            actor_role,
            idempotency_key,
            req_hash if idempotency_key else None,
            Jsonb(record_body) if idempotency_key else None,
        ),
    )
    await audit_store.record(
        conn,
        org_id=org_id,
        actor=person_id,
        action="task.retry",
        subject=f"instance:{instance_id}",
        data={"decision_id": decision_id, "failed_task_id": task_id, "new_task_id": new_task_id},
    )
    return record_body
