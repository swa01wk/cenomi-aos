"""Kernel-opened decisions and decidePending (M2-BE-04)."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from aos.registry.kinds import ArtifactType, WorkflowDecisionSpec, WorkflowDefinition

from . import audit_store, clock, ids, workflow
from .contracts import _canonical_json
from .org import OrgModel
class DecisionError(Exception):
    def __init__(self, code: str, status: int, title: str, detail: str = "", **extra: Any) -> None:
        self.code = code
        self.status = status
        self.title = title
        self.detail = detail
        self.extra = extra
        super().__init__(title)


def _decision_request_hash(pending_id: str, body: dict[str, Any]) -> str:
    payload = {
        "pending_id": pending_id,
        "value": body.get("value"),
        "artifact_version": body.get("artifact_version"),
        "selection": body.get("selection"),
        "expected_version": body.get("expected_version"),
        "note": body.get("note"),
    }
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _decision_name_from_event(event: str) -> str:
    if not event.startswith("decision."):
        raise DecisionError("internal", 500, "Invalid pending event", f"Expected decision.*, got {event!r}.")
    return event.removeprefix("decision.")


async def _load_workflow(
    conn: AsyncConnection, instance_id: str
) -> tuple[str, str, WorkflowDefinition, dict[str, dict[str, dict]]]:
    cur = await conn.execute(
        "select org_id, workflow, pack_version_id from work.instances where id = %s",
        (instance_id,),
    )
    row = await cur.fetchone()
    if row is None:
        raise DecisionError("not_found", 404, "Job not found", f"No instance {instance_id!r}.")
    org_id, workflow_name, pack_version_id = row[0], row[1], str(row[2])
    cur = await conn.execute(
        "select spec from registry.definitions where pack_version_id = %s and kind = 'WorkflowDefinition'"
        " and name = %s",
        (pack_version_id, workflow_name),
    )
    wrow = await cur.fetchone()
    if wrow is None:
        raise DecisionError("internal", 500, "Workflow missing", "Pinned workflow definition not found.")
    wdoc = wrow[0] if isinstance(wrow[0], dict) else json.loads(wrow[0])
    definition = WorkflowDefinition.model_validate(wdoc)
    defs = await workflow._load_definitions(conn, pack_version_id)
    return org_id, workflow_name, definition, defs


async def _regions_ready(
    conn: AsyncConnection,
    instance_id: str,
    join_state: str,
    definition: WorkflowDefinition,
) -> bool:
    required = [r.region for r in definition.spec.parallel if r.join_at == join_state]
    if not required:
        return True
    for name in required:
        cur = await conn.execute(
            "select state from work.regions where instance_id = %s and name = %s",
            (instance_id, name),
        )
        row = await cur.fetchone()
        if row is None or row[0] not in ("done", "joined"):
            return False
    return True


async def _state_tasks_complete(
    conn: AsyncConnection, instance_id: str, templates: list[str]
) -> bool:
    if not templates:
        return True
    cur = await conn.execute(
        "select template, state from work.tasks where instance_id = %s and template = any(%s)",
        (instance_id, templates),
    )
    rows = await cur.fetchall()
    by_template = {t: s for t, s in rows}
    for tpl in templates:
        if by_template.get(tpl) != "COMPLETED":
            return False
    return True


async def pending_for_viewer(
    conn: AsyncConnection,
    instance_id: str,
    person_id: str,
    viewer_roles: list[str],
) -> list[dict[str, Any]]:
    """Open pending items visible to the caller (PendingItem shape)."""
    cur = await conn.execute(
        "select id, instance_id, kind, event, title, detail, for_role, for_person_id,"
        " options, artifact_ref, approval_id, due_at, status, created_at"
        " from work.pending_items where instance_id = %s and status = 'open'"
        " order by created_at",
        (instance_id,),
    )
    out: list[dict[str, Any]] = []
    for row in await cur.fetchall():
        (
            pid,
            inst_id,
            kind,
            event,
            title,
            detail,
            for_role,
            for_person,
            options,
            artifact_ref,
            approval_id,
            due_at,
            status,
            created_at,
        ) = row
        if for_person != person_id and for_role not in viewer_roles:
            continue
        options_doc = options if isinstance(options, list) else json.loads(options or "[]")
        art: dict[str, Any] | None
        if artifact_ref is None:
            art = None
        elif isinstance(artifact_ref, dict):
            art = artifact_ref
        else:
            art = json.loads(artifact_ref)
        created: datetime | str = created_at
        out.append(
            {
                "pending_id": pid,
                "instance_id": inst_id,
                "kind": kind,
                "event": event,
                "title": title,
                "detail": detail or "",
                "for_role": for_role,
                "for_person_id": for_person,
                "options": options_doc,
                "artifact_ref": art,
                "approval_id": approval_id,
                "due_at": due_at.isoformat() if due_at is not None else None,
                "status": status,
                "created_at": created.isoformat() if hasattr(created, "isoformat") else str(created),
            }
        )
    return out


async def _latest_view_artifact(
    conn: AsyncConnection, instance_id: str, view_type: str
) -> tuple[str, int, str] | None:
    cur = await conn.execute(
        "select id, latest_version from work.artifacts"
        " where instance_id = %s and artifact_type = %s and key = ''"
        " order by latest_version desc limit 1",
        (instance_id, view_type),
    )
    row = await cur.fetchone()
    if row is None or int(row[1]) < 1:
        return None
    aid, ver = row[0], int(row[1])
    vcur = await conn.execute(
        "select content_hash from work.artifact_versions where artifact_id = %s and version = %s",
        (aid, ver),
    )
    vrow = await vcur.fetchone()
    if vrow is None:
        return None
    return aid, ver, str(vrow[0])


def _pending_payload(
    *,
    pending_id: str,
    instance_id: str,
    event: str,
    title: str,
    for_role: str,
    for_person_id: str,
    artifact_ref: dict[str, Any] | None,
    created_at: datetime,
) -> dict[str, Any]:
    options = [{"value": "confirm", "label": title}]
    return {
        "pending_id": pending_id,
        "instance_id": instance_id,
        "kind": "decision",
        "event": event,
        "title": title,
        "detail": "",
        "for_role": for_role,
        "for_person_id": for_person_id,
        "options": options,
        "artifact_ref": artifact_ref,
        "approval_id": None,
        "due_at": None,
        "status": "open",
        "created_at": created_at.isoformat(),
    }


async def _emit_pending_created(
    conn: AsyncConnection,
    *,
    instance_id: str,
    person_id: str,
    pending: dict[str, Any],
) -> None:
    from .outbox import OutboxRow, append_outbox_many

    at = pending["created_at"]
    rows = [
        OutboxRow(
            stream=ids.stream_user(person_id),
            event_type="pending.created",
            instance_id=instance_id,
            audience={"person_id": person_id},
            data={"instance_id": instance_id, "pending": pending},
        ),
        OutboxRow(
            stream=ids.stream_instance(instance_id),
            event_type="pending.created",
            instance_id=instance_id,
            audience={"person_id": person_id},
            data={"instance_id": instance_id, "pending": pending},
        ),
    ]
    await append_outbox_many(conn, rows)


async def _emit_pending_resolved(
    conn: AsyncConnection,
    *,
    instance_id: str,
    person_id: str,
    pending_id: str,
    outcome: str,
    by: str,
) -> None:
    from .outbox import OutboxRow, append_outbox_many

    data = {
        "instance_id": instance_id,
        "pending_id": pending_id,
        "outcome": outcome,
        "by": by,
    }
    await append_outbox_many(
        conn,
        [
            OutboxRow(
                stream=ids.stream_user(person_id),
                event_type="pending.resolved",
                instance_id=instance_id,
                audience={"person_id": person_id},
                data=data,
            ),
            OutboxRow(
                stream=ids.stream_instance(instance_id),
                event_type="pending.resolved",
                instance_id=instance_id,
                audience={"person_id": person_id},
                data=data,
            ),
        ],
    )


async def open_ready_decisions(
    conn: AsyncConnection,
    instance_id: str,
    *,
    org: OrgModel,
    packs_dir: Path,
) -> list[str]:
    """Open pending items for decisions whose preconditions hold. Idempotent per decision event."""
    cur = await conn.execute(
        "select state, status from work.instances where id = %s",
        (instance_id,),
    )
    row = await cur.fetchone()
    if row is None or row[1] != "running":
        return []
    state = row[0]
    _org_id, _wf_name, definition, _defs = await _load_workflow(conn, instance_id)
    opened: list[str] = []
    ts = clock.now()
    for dname, dec in definition.spec.decisions.items():
        if dec.state != state:
            continue
        event = f"decision.{dname}"
        open_cur = await conn.execute(
            "select 1 from work.pending_items where instance_id = %s and event = %s and status = 'open' limit 1",
            (instance_id, event),
        )
        if await open_cur.fetchone() is not None:
            continue
        templates = [t.template for t in definition.spec.states[dec.state].tasks]
        if not await _state_tasks_complete(conn, instance_id, templates):
            continue
        if not await _regions_ready(conn, instance_id, dec.state, definition):
            continue
        from . import participants as participant_ops

        person_id = await participant_ops.resolve_participant(
            conn, org, instance_id, dec.for_, packs_dir=packs_dir
        )
        if person_id is None:
            continue
        view = definition.spec.states[dec.state].view
        artifact_ref: dict[str, Any] | None = None
        if view:
            bound = await _latest_view_artifact(conn, instance_id, view)
            if bound is None:
                continue
            aid, ver, ch = bound
            artifact_ref = {"artifact_id": aid, "version": ver, "content_hash": ch}
        pending_id = ids.new_pending_id()
        pending_doc = _pending_payload(
            pending_id=pending_id,
            instance_id=instance_id,
            event=event,
            title=dec.label,
            for_role=dec.for_,
            for_person_id=person_id,
            artifact_ref=artifact_ref,
            created_at=ts,
        )
        await conn.execute(
            "insert into work.pending_items ("
            " id, instance_id, kind, event, title, detail, for_role, for_person_id,"
            " options, artifact_ref, status, created_at"
            ") values (%s, %s, 'decision', %s, %s, '', %s, %s, %s, %s, 'open', %s)",
            (
                pending_id,
                instance_id,
                event,
                dec.label,
                dec.for_,
                person_id,
                Jsonb(pending_doc["options"]),
                Jsonb(artifact_ref) if artifact_ref else None,
                ts,
            ),
        )
        await _emit_pending_created(conn, instance_id=instance_id, person_id=person_id, pending=pending_doc)
        from .progress import post_decision_opened_progress

        inst_org_cur = await conn.execute(
            "select org_id from work.instances where id = %s",
            (instance_id,),
        )
        org_row = await inst_org_cur.fetchone()
        if org_row:
            await post_decision_opened_progress(
                conn,
                org=org,
                org_id=str(org_row[0]),
                instance_id=instance_id,
                pending_id=pending_id,
                label=dec.label,
                for_person_id=person_id,
                for_role=dec.for_,
            )
        opened.append(pending_id)
    return opened


def _row_key_values(content: dict[str, Any], row_key: str) -> set[str]:
    rows = content.get("rows")
    if not isinstance(rows, list):
        return set()
    out: set[str] = set()
    for row in rows:
        if isinstance(row, dict) and row_key in row and row[row_key] is not None:
            out.add(str(row[row_key]))
    return out


def _validate_selection(
    selection: list[str],
    *,
    row_key: str,
    content: dict[str, Any],
) -> None:
    if len(selection) != len(set(selection)):
        raise DecisionError(
            "validation_failed",
            422,
            "Invalid selection",
            "Each item may appear only once.",
        )
    allowed = _row_key_values(content, row_key)
    bad = [s for s in selection if s not in allowed]
    if bad:
        raise DecisionError(
            "validation_failed",
            422,
            "Invalid selection",
            "One or more selected items are not in the current version.",
        )


def _apply_sets(
    attributes: dict[str, Any],
    dec: WorkflowDecisionSpec,
    *,
    artifact_version: int | None,
    selection: list[str] | None,
) -> dict[str, Any]:
    out = dict(attributes)
    for attr_key, setter in dec.sets.items():
        if setter == "artifact_version":
            if artifact_version is None:
                raise DecisionError(
                    "validation_failed",
                    422,
                    "Artifact version required",
                    "This decision is bound to an artifact version.",
                )
            out[attr_key] = int(artifact_version)
        elif setter == "selection_count":
            if selection is None:
                raise DecisionError(
                    "validation_failed",
                    422,
                    "Selection required",
                    "Choose one or more items before confirming.",
                )
            out[attr_key] = len(selection)
    return out


def _decision_record_response(
    *,
    decision_id: str,
    instance_id: str,
    event: str,
    value: str,
    actor: str,
    role: str | None,
    at: datetime,
    artifact_ref: dict[str, Any] | None,
    resulting_state: str | None,
) -> dict[str, Any]:
    return {
        "decision_id": decision_id,
        "instance_id": instance_id,
        "event": event,
        "value": value,
        "by": actor,
        "role": role,
        "at": at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "artifact_ref": artifact_ref,
        "resulting_state": resulting_state,
    }


async def decide_pending(
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

    pend_cur = await conn.execute(
        "select instance_id, kind, event, for_person_id, for_role, artifact_ref, status"
        " from work.pending_items where id = %s",
        (pending_id,),
    )
    pend_row = await pend_cur.fetchone()
    if pend_row is None:
        raise DecisionError("not_found", 404, "Pending item not found", f"No pending item {pending_id!r}.")
    instance_id, kind, event, for_person, for_role, artifact_ref_raw, pend_status = pend_row
    if kind != "decision":
        raise DecisionError("conflict", 409, "Not a decision", "This pending item is not a decision card.")

    inst_cur = await conn.execute(
        "select org_id, workflow, pack_version_id, state, version, status, attributes, correlation_id"
        " from work.instances where id = %s for update",
        (instance_id,),
    )
    inst = await inst_cur.fetchone()
    if inst is None:
        raise DecisionError("not_found", 404, "Job not found", f"No instance {instance_id!r}.")
    (
        inst_org,
        workflow_name,
        pack_version_id,
        from_state,
        inst_version,
        inst_status,
        attributes_raw,
        _correlation_id,
    ) = inst
    if inst_org != org_id:
        raise DecisionError("not_found", 404, "Pending item not found", f"No pending item {pending_id!r}.")

    await conn.execute("select id from work.pending_items where id = %s for update", (pending_id,))
    pend_cur2 = await conn.execute(
        "select status, for_person_id, artifact_ref from work.pending_items where id = %s",
        (pending_id,),
    )
    pend2 = await pend_cur2.fetchone()
    if pend2 is None:
        raise DecisionError("not_found", 404, "Pending item not found", f"No pending item {pending_id!r}.")
    pend_status, for_person, artifact_ref_raw = pend2[0], pend2[1], pend2[2]

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

    expected = body.get("expected_version")
    if expected is None or int(expected) != int(inst_version):
        raise DecisionError(
            "stale_version",
            409,
            "Job changed",
            "Reload the job and try again.",
            current_version=int(inst_version),
        )

    dname = _decision_name_from_event(str(event))
    wcur = await conn.execute(
        "select spec from registry.definitions where pack_version_id = %s and kind = 'WorkflowDefinition'"
        " and name = %s",
        (str(pack_version_id), workflow_name),
    )
    wrow = await wcur.fetchone()
    wdoc = wrow[0] if isinstance(wrow[0], dict) else json.loads(wrow[0])
    definition = WorkflowDefinition.model_validate(wdoc)
    defs = await workflow._load_definitions(conn, str(pack_version_id))
    dec = definition.spec.decisions.get(dname)
    if dec is None:
        raise DecisionError("internal", 500, "Decision undefined", f"No decision {dname!r} on workflow.")

    artifact_ref = artifact_ref_raw if isinstance(artifact_ref_raw, dict) else (
        json.loads(artifact_ref_raw) if artifact_ref_raw else None
    )
    body_artifact_version = body.get("artifact_version")
    bound_content: dict[str, Any] | None = None
    if artifact_ref is not None:
        bound_ver = int(artifact_ref["version"])
        if body_artifact_version is None or int(body_artifact_version) != bound_ver:
            raise DecisionError(
                "stale_version",
                409,
                "Version changed",
                "Reload and confirm the current version.",
                current_version=bound_ver,
            )
        aid = artifact_ref["artifact_id"]
        acur = await conn.execute(
            "select latest_version from work.artifacts where id = %s",
            (aid,),
        )
        arow = await acur.fetchone()
        if arow is None or int(arow[0]) != bound_ver:
            raise DecisionError(
                "stale_version",
                409,
                "Version changed",
                "Reload and confirm the current version.",
                current_version=int(arow[0]) if arow else bound_ver,
            )
        vcur = await conn.execute(
            "select content from work.artifact_versions where artifact_id = %s and version = %s",
            (aid, bound_ver),
        )
        vrow = await vcur.fetchone()
        if vrow is not None:
            bound_content = vrow[0] if isinstance(vrow[0], dict) else json.loads(vrow[0])

    selection = body.get("selection")
    if dec.selection and (selection is None or not isinstance(selection, list) or len(selection) == 0):
        raise DecisionError(
            "validation_failed",
            422,
            "Selection required",
            "Choose one or more items before confirming.",
        )
    if dec.selection and isinstance(selection, list):
        # Fail closed: a selection is only accepted when it can be checked against the bound rows.
        view_name = definition.spec.states[dec.state].view
        raw_at = defs.get("ArtifactType", {}).get(view_name) if view_name else None
        at = ArtifactType.model_validate(raw_at) if raw_at is not None else None
        if (
            artifact_ref is None
            or bound_content is None
            or at is None
            or not at.spec.row_based
            or not at.spec.row_key
        ):
            raise DecisionError(
                "validation_failed",
                422,
                "Invalid selection",
                "There are no rows to select from for this decision.",
            )
        _validate_selection(
            [str(s) for s in selection],
            row_key=at.spec.row_key,
            content=bound_content,
        )

    attributes = attributes_raw if isinstance(attributes_raw, dict) else json.loads(attributes_raw or "{}")
    new_attributes = _apply_sets(
        attributes,
        dec,
        artifact_version=int(body_artifact_version) if body_artifact_version is not None else None,
        selection=selection if isinstance(selection, list) else None,
    )
    changed_attrs = {k for k in dec.sets if attributes.get(k) != new_attributes.get(k)}

    value = str(body.get("value") or "confirm")
    ts = clock.now()
    decision_id = ids.new_decision_id()
    roles = await conn.execute(
        "select role from work.participants where instance_id = %s and person_id = %s",
        (instance_id, person_id),
    )
    actor_roles = [r[0] for r in await roles.fetchall()]
    actor_role = actor_roles[0] if actor_roles else for_role

    selection_json = Jsonb(selection) if isinstance(selection, list) else None
    await conn.execute(
        "update work.instances set attributes = %s where id = %s",
        (Jsonb(new_attributes), instance_id),
    )

    await conn.execute(
        "update work.pending_items set status = 'resolved', resolved_at = %s, resolved_by = %s where id = %s",
        (ts, person_id, pending_id),
    )
    await _emit_pending_resolved(
        conn,
        instance_id=instance_id,
        person_id=person_id,
        pending_id=pending_id,
        outcome="resolved",
        by=person_id,
    )
    apply_result = await workflow.apply_event(
        conn,
        instance_id,
        str(event),
        by_role=dec.for_,
        decision_id=decision_id,
        packs_dir=packs_dir,
        org=org,
        actor={"kind": "person", "id": person_id},
    )
    resulting_state = apply_result.to_state if apply_result.applied else from_state

    from . import events as workflow_events

    await workflow_events.evaluate_attribute_triggers(
        conn,
        org,
        instance_id,
        changed=changed_attrs,
        packs_dir=packs_dir,
    )

    from .progress import post_decision_resolved_progress

    from_spec = definition.spec.states.get(from_state) if from_state else None
    unchanged_label = from_spec.label if from_spec is not None else from_state
    await post_decision_resolved_progress(
        conn,
        org=org,
        org_id=org_id,
        instance_id=instance_id,
        decider_id=person_id,
        decision_label=dec.label,
        job_moved=apply_result.applied,
        state_label_if_unchanged=str(unchanged_label or from_state),
    )

    if apply_result.applied and artifact_ref is not None:
        await conn.execute(
            "update work.artifacts set status = 'final' where id = %s",
            (artifact_ref["artifact_id"],),
        )

    record_body = _decision_record_response(
        decision_id=decision_id,
        instance_id=instance_id,
        event=str(event),
        value=value,
        actor=person_id,
        role=actor_role,
        at=ts,
        artifact_ref=artifact_ref,
        resulting_state=resulting_state,
    )

    await conn.execute(
        "insert into gov.decision_records ("
        " id, org_id, subject_kind, subject_id, event, value, actor, actor_role,"
        " artifact_ref, selection, idempotency_key, request_hash, response"
        ") values (%s, %s, 'instance', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            decision_id,
            org_id,
            instance_id,
            str(event),
            value,
            person_id,
            actor_role,
            Jsonb(artifact_ref) if artifact_ref else None,
            selection_json,
            idempotency_key,
            req_hash if idempotency_key else None,
            Jsonb(record_body) if idempotency_key else None,
        ),
    )
    await audit_store.record(
        conn,
        org_id=org_id,
        actor=person_id,
        action=str(event),
        subject=f"instance:{instance_id}",
        data={"decision_id": decision_id, "value": value, "resulting_state": resulting_state},
    )

    await open_ready_decisions(conn, instance_id, org=org, packs_dir=packs_dir)

    return record_body


async def void_open_decisions_for_artifact(
    conn: AsyncConnection,
    *,
    instance_id: str,
    artifact_id: str,
    voided_by: str,
) -> int:
    """Void every open decision pending bound to this artifact. Returns how many were voided."""
    cur = await conn.execute(
        "select id, for_person_id from work.pending_items"
        " where instance_id = %s and status = 'open' and kind = 'decision'"
        " and artifact_ref->>'artifact_id' = %s"
        " for update",
        (instance_id, artifact_id),
    )
    rows = await cur.fetchall()
    if not rows:
        return 0
    ts = clock.now()
    for pending_id, for_person in rows:
        await conn.execute(
            "update work.pending_items set status = 'voided', resolved_at = %s, resolved_by = %s where id = %s",
            (ts, voided_by, pending_id),
        )
        await _emit_pending_resolved(
            conn,
            instance_id=instance_id,
            person_id=for_person,
            pending_id=pending_id,
            outcome="voided",
            by=voided_by,
        )
    return len(rows)
