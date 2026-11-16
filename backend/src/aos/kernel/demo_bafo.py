"""Demo: BAFO send approvals and opening the next negotiation card."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from aos.connectors.demo_proposal_fill import demo_supplier_display_name
from aos.connectors.demo_rfp_modules import suppliers_with_bafo_outliers

from . import clock, ids
from .org import OrgModel


async def _bafo_queue(conn: AsyncConnection, instance_id: str) -> list[str]:
    """Supplier ids with BAFO drafts not yet marked sent (demo attribute)."""
    cur = await conn.execute("select attributes from work.instances where id = %s", (instance_id,))
    row = await cur.fetchone()
    attrs: dict[str, Any] = {}
    if row and row[0]:
        attrs = row[0] if isinstance(row[0], dict) else json.loads(row[0] or "{}")
    sent_raw = attrs.get("bafo_sent_suppliers")
    sent: set[str] = set()
    if isinstance(sent_raw, list):
        sent = {str(s) for s in sent_raw}
    candidates = suppliers_with_bafo_outliers()
    return [sid for sid in candidates if sid not in sent]


async def _mark_bafo_sent(conn: AsyncConnection, instance_id: str, supplier_id: str) -> None:
    cur = await conn.execute("select attributes from work.instances where id = %s", (instance_id,))
    row = await cur.fetchone()
    attrs: dict[str, Any] = {}
    if row and row[0]:
        attrs = dict(row[0] if isinstance(row[0], dict) else json.loads(row[0] or "{}"))
    sent_raw = attrs.get("bafo_sent_suppliers")
    sent = [str(s) for s in sent_raw] if isinstance(sent_raw, list) else []
    if supplier_id not in sent:
        sent.append(supplier_id)
    attrs["bafo_sent_suppliers"] = sent
    await conn.execute(
        "update work.instances set attributes = %s where id = %s",
        (Jsonb(attrs), instance_id),
    )


async def open_next_bafo_pending(
    conn: AsyncConnection,
    org: OrgModel,
    instance_id: str,
    *,
    packs_dir: Path,
) -> str | None:
    from . import decisions as decision_ops
    from . import participants as participant_ops

    queue = await _bafo_queue(conn, instance_id)
    if not queue:
        return await _open_bafo_round_complete(conn, org, instance_id, packs_dir=packs_dir)

    supplier_id = queue[0]
    cur = await conn.execute(
        "select a.id, a.latest_version, v.content_hash, v.content"
        " from work.artifacts a"
        " join work.artifact_versions v on v.artifact_id = a.id and v.version = a.latest_version"
        " where a.instance_id = %s and a.artifact_type = 'bafo_email' and a.key = %s limit 1",
        (instance_id, supplier_id),
    )
    row = await cur.fetchone()
    if row is None:
        return await _open_bafo_round_complete(conn, org, instance_id, packs_dir=packs_dir)

    aid, ver, ch, content_raw = row[0], int(row[1]), str(row[2]), row[3]
    content = content_raw if isinstance(content_raw, dict) else json.loads(content_raw or "{}")
    name = demo_supplier_display_name(supplier_id)

    open_cur = await conn.execute(
        "select 1 from work.pending_items where instance_id = %s and event = %s and status = 'open' limit 1",
        (instance_id, "decision.bafo_send_approved"),
    )
    if await open_cur.fetchone() is not None:
        return None

    person_id = await participant_ops.resolve_participant(
        conn, org, instance_id, "buyer", packs_dir=packs_dir
    )
    if person_id is None:
        return None

    artifact_ref = {
        "artifact_id": aid,
        "version": ver,
        "content_hash": ch,
        "supplier_id": supplier_id,
    }
    detail = (
        f"Review the BAFO draft for {name} in the work panel (Drafts). It challenges module prices "
        "against peer submissions — edit if needed, then approve to send on the RFP thread."
    )
    ts = clock.now()
    pending_id = ids.new_pending_id()
    pending_doc = decision_ops._pending_payload(
        pending_id=pending_id,
        instance_id=instance_id,
        event="decision.bafo_send_approved",
        title=f"Send BAFO to {name}",
        for_role="buyer",
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
            "decision.bafo_send_approved",
            pending_doc["title"],
            detail,
            "buyer",
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
            for_role="buyer",
        )
    return pending_id


async def _open_bafo_round_complete(
    conn: AsyncConnection,
    org: OrgModel,
    instance_id: str,
    *,
    packs_dir: Path,
) -> str | None:
    from . import decisions as decision_ops
    from . import participants as participant_ops

    open_cur = await conn.execute(
        "select 1 from work.pending_items where instance_id = %s and event = %s and status = 'open' limit 1",
        (instance_id, "decision.bafo_round_complete"),
    )
    if await open_cur.fetchone() is not None:
        return None

    person_id = await participant_ops.resolve_participant(
        conn, org, instance_id, "buyer", packs_dir=packs_dir
    )
    if person_id is None:
        return None

    detail = (
        "All BAFO messages are sent. Confirm to refresh module scores from vendor responses "
        "and return to evaluation for category-head vendor recommendation."
    )
    ts = clock.now()
    pending_id = ids.new_pending_id()
    pending_doc = decision_ops._pending_payload(
        pending_id=pending_id,
        instance_id=instance_id,
        event="decision.bafo_round_complete",
        title="Complete BAFO round",
        for_role="buyer",
        for_person_id=person_id,
        artifact_ref=None,
        created_at=ts,
        detail=detail,
        select_min=None,
    )
    await conn.execute(
        "insert into work.pending_items ("
        " id, instance_id, kind, event, title, detail, for_role, for_person_id,"
        " options, artifact_ref, status, created_at"
        ") values (%s, %s, 'decision', %s, %s, %s, %s, %s, %s, null, 'open', %s)",
        (
            pending_id,
            instance_id,
            "decision.bafo_round_complete",
            pending_doc["title"],
            detail,
            "buyer",
            person_id,
            Jsonb(pending_doc["options"]),
            ts,
        ),
    )
    await decision_ops._emit_pending_created(
        conn, instance_id=instance_id, person_id=person_id, pending=pending_doc
    )
    return pending_id


async def send_bafo_after_approve(
    conn: AsyncConnection,
    org: OrgModel,
    instance_id: str,
    *,
    artifact_ref: dict[str, Any],
    email_content: dict[str, Any],
    approver_id: str,
    org_id: str,
    packs_dir: Path,
) -> None:
    from .conversation import insert_person_turn
    from .progress import post_decision_resolved_progress

    supplier_id = str(artifact_ref.get("supplier_id") or email_content.get("supplier_id") or "")
    name = demo_supplier_display_name(supplier_id)
    body = str(email_content.get("body") or "").strip()
    if not body:
        body = f"BAFO module pricing review sent to {name}."

    roles_cur = await conn.execute(
        "select role from work.participants where instance_id = %s order by role",
        (instance_id,),
    )
    roles = [str(r[0]) for r in await roles_cur.fetchall()]
    await insert_person_turn(
        conn,
        instance_id=instance_id,
        person_id=approver_id,
        text=f"Sent BAFO (module pricing) to {name} on the RFP thread:\n\n{body}",
        client_turn_id=f"demo-bafo-{instance_id}-{supplier_id}",
        audience_roles=roles,
    )
    await _mark_bafo_sent(conn, instance_id, supplier_id)

    await post_decision_resolved_progress(
        conn,
        org=org,
        org_id=org_id,
        instance_id=instance_id,
        decider_id=approver_id,
        decision_label="Approve and send BAFO message",
        job_moved=False,
        state_label_if_unchanged="BAFO negotiation",
        selection=None,
        row_key=None,
        bound_content=email_content,
        note=None,
    )
    await open_next_bafo_pending(conn, org, instance_id, packs_dir=packs_dir)


async def apply_post_bafo_eval_refresh(conn: AsyncConnection, instance_id: str) -> None:
    """Replace module matrix/scores with post-BAFO pricing (demo)."""
    from aos.connectors.demo_rfp_modules import build_module_matrix_rows, build_module_score_rows

    from .conversation import insert_agent_turn, text_blocks

    await insert_agent_turn(
        conn,
        instance_id=instance_id,
        seat_id="seat_sourcing_poc",
        seat_name="Noor Al-Rashid",
        blocks=text_blocks(
            "Vendors replied to BAFO on the thread. **Module comparison** and **Module scores** now reflect "
            "revised module pricing (Peninsula trimmed hosting, Rawabi trimmed API). **Rami** can recommend a "
            "vendor from the weighted evaluation."
        ),
        audience_roles=None,
        attempt_id=None,
    )

    matrix = {"rows": build_module_matrix_rows(post_bafo=True)}
    scores = {"rows": build_module_score_rows(post_bafo=True)}

    for artifact_type, content in (
        ("rfp_module_matrix", matrix),
        ("rfp_module_scores", scores),
    ):
        cur = await conn.execute(
            "select id, latest_version from work.artifacts"
            " where instance_id = %s and artifact_type = %s limit 1",
            (instance_id, artifact_type),
        )
        row = await cur.fetchone()
        if row is None:
            continue
        aid, ver = row[0], int(row[1]) + 1
        import hashlib

        ch = hashlib.sha256(
            json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        await conn.execute(
            "insert into work.artifact_versions (artifact_id, version, content, content_hash,"
            " produced_by_kind, produced_by, inputs, sources)"
            " values (%s, %s, %s, %s, 'person', 'noura', '[]'::jsonb, '[]'::jsonb)",
            (aid, ver, Jsonb(content), ch),
        )
        await conn.execute(
            "update work.artifacts set latest_version = %s, status = 'final' where id = %s",
            (ver, aid),
        )
