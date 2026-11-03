"""Kernel-posted progress turns (M2-BE-07, ADR 015)."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from aos.registry.kinds import ArtifactType, WorkflowDefinition

from . import ids
from .contracts import _class_rank, participant_classification_ceiling
from .conversation import insert_agent_turn, insert_person_turn, project_turn, text_blocks
from .org import OrgModel
from .outbox import OutboxRow, append_outbox_many
from .worker_attempts import seat_display_name


async def _state_label(
    conn: AsyncConnection,
    *,
    pack_version_id: str,
    workflow_name: str,
    state_name: str,
) -> str:
    cur = await conn.execute(
        "select spec from registry.definitions where pack_version_id = %s and kind = 'WorkflowDefinition'"
        " and name = %s",
        (pack_version_id, workflow_name),
    )
    row = await cur.fetchone()
    if row is None:
        return state_name
    wdoc = row[0] if isinstance(row[0], dict) else json.loads(row[0])
    states = (wdoc.get("spec") or {}).get("states") or {}
    spec = states.get(state_name) or {}
    return str(spec.get("label") or state_name)


def _progress_text(summary: str | None, *, fallback: str) -> str:
    text = (summary or "").strip()
    return text if text else fallback


def _summary_for_reader(
    summary: str | None,
    *,
    contract: dict[str, Any],
    seat_doc: dict[str, Any],
    defs: dict[str, dict[str, dict]],
    org: OrgModel,
    person_id: str,
    fallback: str,
) -> str:
    ceiling = (contract.get("permission_scope") or {}).get("classification_ceiling") or "internal"
    clearance = participant_classification_ceiling(seat_doc, defs, org=org, person_id=person_id)
    if _class_rank(str(ceiling)) > _class_rank(str(clearance)):
        return fallback
    return _progress_text(summary, fallback=fallback)


async def post_agent_progress_turn(
    conn: AsyncConnection,
    *,
    org: OrgModel,
    org_id: str,
    instance_id: str,
    seat_name: str,
    seat_version: int,
    blocks: list[dict[str, Any]],
    audience: dict[str, Any],
    attempt_id: str | None = None,
) -> dict[str, Any]:
    author_name = await seat_display_name(
        conn, org_id=org_id, seat_name=seat_name, seat_version=seat_version
    )
    outbox_audience = {k: v for k, v in audience.items() if k != "roles"}
    turn = await insert_agent_turn(
        conn,
        instance_id=instance_id,
        seat_id=seat_name,
        seat_name=author_name,
        blocks=blocks,
        audience_roles=audience.get("roles"),
        attempt_id=attempt_id,
    )
    turn_payload = {
        "turn_id": turn["turn_id"],
        "seq": turn["seq"],
        "author": turn["author"],
        "blocks": turn["blocks"],
        "at": turn["at"],
        "attempt_id": turn["attempt_id"],
    }
    await append_outbox_many(
        conn,
        [
            OutboxRow(
                stream=ids.stream_instance(instance_id),
                event_type="agent.message.completed",
                instance_id=instance_id,
                audience=outbox_audience,
                data={"instance_id": instance_id, "turn": turn_payload},
            )
        ],
    )
    return turn_payload


async def post_task_outcome_progress(
    conn: AsyncConnection,
    *,
    org: OrgModel,
    org_id: str,
    instance_id: str,
    task_id: str,
    summary: str | None,
    attempt_id: str | None = None,
) -> None:
    from .instances import _load_definitions

    icur = await conn.execute(
        "select seat, seat_version, workflow, pack_version_id, state from work.instances where id = %s",
        (instance_id,),
    )
    inst = await icur.fetchone()
    if inst is None:
        return
    seat_name, seat_version, workflow_name, pvid, instance_state = inst
    tcur = await conn.execute(
        "select contract from work.tasks where id = %s",
        (task_id,),
    )
    trow = await tcur.fetchone()
    if trow is None:
        return
    contract = trow[0] if isinstance(trow[0], dict) else json.loads(trow[0])
    on_behalf = contract.get("on_behalf_of") or {}
    role = on_behalf.get("role")
    if not role:
        return
    from . import participants as participant_ops

    person_id = await participant_ops.resolve_participant(conn, org, instance_id, role)
    if person_id is None:
        return
    fallback = await _state_label(
        conn,
        pack_version_id=str(pvid),
        workflow_name=str(workflow_name),
        state_name=str(instance_state),
    )
    defs = await _load_definitions(conn, str(pvid))
    seat_doc = defs.get("Seat", {}).get(seat_name) or {}
    text = _summary_for_reader(
        summary,
        contract=contract,
        seat_doc=seat_doc,
        defs=defs,
        org=org,
        person_id=str(person_id),
        fallback=fallback,
    )
    role_list = [str(role)] if role else None
    audience: dict[str, Any] = {"person_id": str(person_id)}
    if role_list:
        audience["roles"] = role_list
    await post_agent_progress_turn(
        conn,
        org=org,
        org_id=org_id,
        instance_id=instance_id,
        seat_name=str(seat_name),
        seat_version=int(seat_version),
        blocks=text_blocks(text),
        audience=audience,
        attempt_id=attempt_id,
    )


async def post_decision_opened_progress(
    conn: AsyncConnection,
    *,
    org: OrgModel,
    org_id: str,
    instance_id: str,
    pending_id: str,
    label: str,
    for_person_id: str,
    for_role: str,
) -> None:
    icur = await conn.execute(
        "select seat, seat_version from work.instances where id = %s",
        (instance_id,),
    )
    inst = await icur.fetchone()
    if inst is None:
        return
    seat_name, seat_version = inst
    blocks: list[dict[str, Any]] = [
        {"kind": "text", "text": label},
        {"kind": "pending_ref", "pending_id": pending_id},
    ]
    await post_agent_progress_turn(
        conn,
        org=org,
        org_id=org_id,
        instance_id=instance_id,
        seat_name=str(seat_name),
        seat_version=int(seat_version),
        blocks=blocks,
        audience={"person_id": for_person_id, "roles": [for_role]},
        attempt_id=None,
    )


def format_decision_person_text(
    *,
    decision_label: str,
    job_moved: bool,
    state_label_if_unchanged: str,
    selection: list[str] | None = None,
    row_key: str | None = None,
    bound_content: dict[str, Any] | None = None,
    note: str | None = None,
) -> str:
    label = decision_label.strip().rstrip(".")
    if selection and row_key and bound_content:
        rows = bound_content.get("rows")
        by_key: dict[str, dict[str, Any]] = {}
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict) and row.get(row_key) is not None:
                    by_key[str(row[row_key])] = row
        picked: list[str] = []
        for sid in selection:
            row = by_key.get(str(sid), {})
            name = row.get("supplier") or row.get("name") or sid
            name_s = str(name).strip()
            sid_s = str(sid)
            if sid_s and sid_s not in name_s:
                picked.append(f"- {name_s} ({sid_s})")
            else:
                picked.append(f"- {name_s}")
        if picked:
            if job_moved and "award" in label.lower():
                vendor_line = picked[0].lstrip("- ").strip()
                vendor_name = vendor_line.split(" (", 1)[0].strip()
                lines = [f"Awarded this order to {vendor_name}."]
            elif job_moved:
                lines = [f"{label}."]
                lines.append("")
                lines.append("Selected suppliers:")
                lines.extend(picked)
            else:
                lines = [f"{label} recorded — still in {state_label_if_unchanged}."]
                lines.append("")
                lines.append("Selected suppliers:")
                lines.extend(picked)
        elif job_moved:
            lines = [f"{label}."]
        else:
            lines = [f"{label} recorded — still in {state_label_if_unchanged}."]
    elif job_moved:
        lines = [f"{label}."]
    else:
        lines = [f"{label} recorded — still in {state_label_if_unchanged}."]
    note_s = (note or "").strip()
    if note_s:
        lines.append("")
        lines.append(note_s)
    return "\n".join(lines)


def _turn_text(blocks: Any) -> str:
    if not isinstance(blocks, list):
        return ""
    for block in blocks:
        if isinstance(block, dict) and block.get("kind") == "text" and isinstance(block.get("text"), str):
            return block["text"]
    return ""


def _label_matches_turn(label: str, turn_text: str) -> bool:
    norm_label = label.strip().rstrip(".").lower()
    first = turn_text.strip().split("\n", 1)[0].strip().rstrip(".").lower()
    if first == norm_label:
        return True
    if first.startswith(norm_label + " recorded"):
        return True
    return False


async def heal_legacy_selection_decision_turns(
    conn: AsyncConnection,
    *,
    org_id: str,
    instance_id: str,
) -> None:
    """Backfill person-turn text for selection decisions recorded before selection lines were posted."""
    from . import workflow

    icur = await conn.execute(
        "select workflow, pack_version_id from work.instances where id = %s and org_id = %s",
        (instance_id, org_id),
    )
    irow = await icur.fetchone()
    if irow is None:
        return
    workflow_name, pack_version_id = str(irow[0]), str(irow[1])
    defs = await workflow._load_definitions(conn, pack_version_id)
    wdoc = defs.get("WorkflowDefinition", {}).get(workflow_name)
    if wdoc is None:
        return
    definition = WorkflowDefinition.model_validate(wdoc)

    dcur = await conn.execute(
        "select event, actor, selection, artifact_ref, response, at"
        " from gov.decision_records"
        " where org_id = %s and subject_kind = 'instance' and subject_id = %s"
        " and selection is not null and jsonb_array_length(selection) > 0"
        " and event like %s"
        " order by at",
        (org_id, instance_id, "decision.%"),
    )
    for event, actor, selection_raw, artifact_ref_raw, response_raw, decided_at in await dcur.fetchall():
        if not event.startswith("decision."):
            continue
        dname = event.removeprefix("decision.")
        dec = definition.spec.decisions.get(dname)
        if dec is None or not dec.selection:
            continue
        selection: list[str] | None = None
        if isinstance(selection_raw, list):
            selection = [str(s) for s in selection_raw]
        elif isinstance(selection_raw, str):
            try:
                parsed = json.loads(selection_raw)
                if isinstance(parsed, list):
                    selection = [str(s) for s in parsed]
            except json.JSONDecodeError:
                selection = None
        if not selection:
            continue

        artifact_ref = (
            artifact_ref_raw
            if isinstance(artifact_ref_raw, dict)
            else (json.loads(artifact_ref_raw) if artifact_ref_raw else None)
        )
        bound_content: dict[str, Any] | None = None
        row_key: str | None = None
        view_name = definition.spec.states[dec.state].view if dec.state in definition.spec.states else None
        if view_name:
            raw_at = defs.get("ArtifactType", {}).get(str(view_name))
            at = ArtifactType.model_validate(raw_at) if raw_at is not None else None
            if at is not None and at.spec.row_key:
                row_key = str(at.spec.row_key)
        if artifact_ref is not None and row_key:
            aid = artifact_ref.get("artifact_id")
            ver = artifact_ref.get("version")
            if aid is not None and ver is not None:
                vcur = await conn.execute(
                    "select content from work.artifact_versions where artifact_id = %s and version = %s",
                    (str(aid), int(ver)),
                )
                vrow = await vcur.fetchone()
                if vrow is not None:
                    bound_content = vrow[0] if isinstance(vrow[0], dict) else json.loads(vrow[0])

        response = (
            response_raw
            if isinstance(response_raw, dict)
            else (json.loads(response_raw) if response_raw else {})
        )
        resulting_state = response.get("resulting_state") if isinstance(response, dict) else None
        from_spec = definition.spec.states.get(dec.state)
        unchanged_label = from_spec.label if from_spec is not None else dec.state
        job_moved = resulting_state is not None and str(resulting_state) != str(dec.state)

        window_start = decided_at - timedelta(minutes=5)
        window_end = decided_at + timedelta(minutes=5)
        tcur = await conn.execute(
            "select id, blocks from work.turns"
            " where instance_id = %s and author_kind = 'person' and author_id = %s"
            " and at between %s and %s"
            " order by abs(extract(epoch from (at - %s)))",
            (instance_id, str(actor), window_start, window_end, decided_at),
        )
        for turn_id, blocks in await tcur.fetchall():
            turn_text = _turn_text(blocks)
            if not turn_text or "Selected suppliers:" in turn_text:
                continue
            if not _label_matches_turn(dec.label, turn_text):
                continue
            new_text = format_decision_person_text(
                decision_label=dec.label,
                job_moved=job_moved,
                state_label_if_unchanged=str(unchanged_label or dec.state),
                selection=selection,
                row_key=row_key,
                bound_content=bound_content,
            )
            if new_text.strip() == turn_text.strip():
                continue
            await conn.execute(
                "update work.turns set blocks = %s where id = %s",
                (Jsonb(text_blocks(new_text)), turn_id),
            )
            break


async def post_decision_resolved_progress(
    conn: AsyncConnection,
    *,
    org: OrgModel,
    org_id: str,
    instance_id: str,
    decider_id: str,
    decision_label: str,
    job_moved: bool,
    state_label_if_unchanged: str,
    selection: list[str] | None = None,
    row_key: str | None = None,
    bound_content: dict[str, Any] | None = None,
    note: str | None = None,
) -> None:
    text = format_decision_person_text(
        decision_label=decision_label,
        job_moved=job_moved,
        state_label_if_unchanged=state_label_if_unchanged,
        selection=selection,
        row_key=row_key,
        bound_content=bound_content,
        note=note,
    )
    pcur = await conn.execute(
        "select role from work.participants where instance_id = %s",
        (instance_id,),
    )
    roles = [r[0] for r in await pcur.fetchall()]
    turn = await insert_person_turn(
        conn,
        instance_id=instance_id,
        person_id=decider_id,
        text=text,
        client_turn_id=ids.new_turn_id(),
        audience_roles=roles,
        attempt_id=None,
    )
    name = org.people[decider_id].name if decider_id in org.people else decider_id
    tcur = await conn.execute(
        "select id, seq, author_kind, author_id, audience_roles, blocks, attempt_id, at"
        " from work.turns where id = %s",
        (turn["turn_id"],),
    )
    trow = await tcur.fetchone()
    if trow is None:
        return
    turn_payload = project_turn(trow, person_name=name)
    await append_outbox_many(
        conn,
        [
            OutboxRow(
                stream=ids.stream_instance(instance_id),
                event_type="turn.created",
                instance_id=instance_id,
                audience={"roles": roles},
                data={"instance_id": instance_id, "turn": turn_payload},
            )
        ],
    )
