"""Kernel-posted progress turns (M2-BE-07, ADR 015)."""

from __future__ import annotations

import json
from typing import Any

from psycopg import AsyncConnection

from . import ids
from .contracts import _class_rank, participant_classification_ceiling
from .conversation import insert_agent_turn, text_blocks
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
    pcur = await conn.execute(
        "select person_id from work.participants where instance_id = %s and role = %s",
        (instance_id, role),
    )
    prow = await pcur.fetchone()
    if prow is None:
        return
    person_id = prow[0]
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
) -> None:
    icur = await conn.execute(
        "select seat, seat_version from work.instances where id = %s",
        (instance_id,),
    )
    inst = await icur.fetchone()
    if inst is None:
        return
    seat_name, seat_version = inst
    name = org.people[decider_id].name if decider_id in org.people else decider_id
    if job_moved:
        text = f"{name} decided: {decision_label}."
    else:
        text = (
            f"{name}'s decision on '{decision_label}' was recorded; "
            f"the job is still in {state_label_if_unchanged}."
        )
    pcur = await conn.execute(
        "select role from work.participants where instance_id = %s",
        (instance_id,),
    )
    roles = [r[0] for r in await pcur.fetchall()]
    await post_agent_progress_turn(
        conn,
        org=org,
        org_id=org_id,
        instance_id=instance_id,
        seat_name=str(seat_name),
        seat_version=int(seat_version),
        blocks=text_blocks(text),
        audience={"roles": roles},
        attempt_id=None,
    )
