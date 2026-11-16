"""Demo: route vendor clarifications — commercial to buyer, technical to category manager."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from . import clock, ids
from .org import OrgModel


def _draft_answer_from_notes(notes: str) -> str:
    text = notes.strip()
    m = re.search(r"before send:\s*(.+)$", text, re.I | re.S)
    if m:
        return m.group(1).strip()
    return text


def _question_lane(content: dict[str, Any]) -> str:
    lane = str(content.get("question_lane") or "technical").strip().lower()
    return "commercial" if lane == "commercial" else "technical"


async def _insert_clarification_pending(
    conn: AsyncConnection,
    org: OrgModel,
    instance_id: str,
    *,
    event: str,
    title: str,
    detail: str,
    for_role: str,
    person_id: str,
    artifact_ref: dict[str, Any],
) -> str | None:
    from . import decisions as decision_ops

    open_cur = await conn.execute(
        "select id from work.pending_items where instance_id = %s and event = %s and status = 'open' limit 1",
        (instance_id, event),
    )
    if await open_cur.fetchone() is not None:
        return None

    ts = clock.now()
    pending_id = ids.new_pending_id()
    pending_doc = decision_ops._pending_payload(
        pending_id=pending_id,
        instance_id=instance_id,
        event=event,
        title=title,
        for_role=for_role,
        for_person_id=person_id,
        artifact_ref=artifact_ref,
        created_at=ts,
        detail=detail,
        select_min=None,
    )
    await conn.execute(
        "insert into work.pending_items ("
        " id, instance_id, kind, event, title, detail, for_role, for_person_id,"
        " options, artifact_ref, status, created_at"
        ") values (%s, %s, 'decision', %s, %s, %s, %s, %s, %s, %s, 'open', %s)",
        (
            pending_id,
            instance_id,
            event,
            pending_doc["title"],
            detail,
            for_role,
            person_id,
            Jsonb(pending_doc["options"]),
            Jsonb(artifact_ref),
            ts,
        ),
    )
    await decision_ops._emit_pending_created(
        conn, instance_id=instance_id, person_id=person_id, pending=pending_doc
    )
    from .progress import post_decision_opened_progress

    inst_org_cur = await conn.execute("select org_id from work.instances where id = %s", (instance_id,))
    org_row = await inst_org_cur.fetchone()
    if org_row:
        await post_decision_opened_progress(
            conn,
            org=org,
            org_id=str(org_row[0]),
            instance_id=instance_id,
            pending_id=pending_id,
            label=pending_doc["title"],
            for_person_id=person_id,
            for_role=for_role,
        )
    return pending_id


async def open_clarification_pending(
    conn: AsyncConnection,
    org: OrgModel,
    instance_id: str,
    *,
    supplier_id: str,
    question_index: int,
    proposal_artifact_id: str,
    proposal_version: int,
    content_hash: str,
    proposal_content: dict[str, Any],
    packs_dir: Path,
) -> str | None:
    """Open buyer or category-manager decision based on question_lane."""
    from . import participants as participant_ops
    from aos.connectors.demo_proposal_fill import demo_supplier_display_name

    lane = _question_lane(proposal_content)
    name = demo_supplier_display_name(supplier_id)
    artifact_ref = {
        "artifact_id": proposal_artifact_id,
        "version": proposal_version,
        "content_hash": content_hash,
        "supplier_id": supplier_id,
        "question_index": question_index,
        "question_lane": lane,
    }

    if lane == "commercial":
        person_id = await participant_ops.resolve_participant(
            conn, org, instance_id, "buyer", packs_dir=packs_dir
        )
        if person_id is None:
            return None
        return await _insert_clarification_pending(
            conn,
            org,
            instance_id,
            event="decision.clarification_commercial_approved",
            title=f"Send commercial clarification to {name}",
            detail=(
                f"{name} asked a commercial clarification (question {question_index}). "
                "Review or edit the draft in the proposal notes, then approve to send on the RFP thread."
            ),
            for_role="buyer",
            person_id=person_id,
            artifact_ref=artifact_ref,
        )

    person_id = await participant_ops.resolve_participant(
        conn, org, instance_id, "category_manager", packs_dir=packs_dir
    )
    if person_id is None:
        return None
    return await _insert_clarification_pending(
        conn,
        org,
        instance_id,
        event="decision.clarification_send_approved",
        title=f"Send technical clarification to {name}",
        detail=(
            f"{name} asked a technical clarification (question {question_index}). "
            "Correct the draft answer in the proposal notes if needed, then approve to send."
        ),
        for_role="category_manager",
        person_id=person_id,
        artifact_ref=artifact_ref,
    )


async def send_clarification_after_approve(
    conn: AsyncConnection,
    org: OrgModel,
    instance_id: str,
    *,
    artifact_ref: dict[str, Any],
    proposal_content: dict[str, Any],
    approver_id: str,
    org_id: str,
    *,
    lane_label: str,
) -> None:
    from aos.connectors.demo_proposal_fill import demo_supplier_display_name
    from .conversation import insert_person_turn
    from .progress import post_decision_resolved_progress

    supplier_id = str(artifact_ref.get("supplier_id") or "")
    name = demo_supplier_display_name(supplier_id)
    answer = _draft_answer_from_notes(str(proposal_content.get("notes") or ""))
    if not answer:
        answer = "Please see the master RFP for scope details."

    roles_cur = await conn.execute(
        "select role from work.participants where instance_id = %s order by role",
        (instance_id,),
    )
    roles = [str(r[0]) for r in await roles_cur.fetchall()]
    await insert_person_turn(
        conn,
        instance_id=instance_id,
        person_id=approver_id,
        text=f"Sent {lane_label} clarification to {name} on the RFP thread:\n\n{answer}",
        client_turn_id=f"demo-clarify-{instance_id}-{supplier_id}-{artifact_ref.get('question_index')}-{lane_label}",
        audience_roles=roles,
    )

    await post_decision_resolved_progress(
        conn,
        org=org,
        org_id=org_id,
        instance_id=instance_id,
        decider_id=approver_id,
        decision_label=f"Approve and send {lane_label} clarification answer",
        job_moved=False,
        state_label_if_unchanged="Awaiting proposals",
        selection=None,
        row_key=None,
        bound_content=proposal_content,
        note=None,
    )
