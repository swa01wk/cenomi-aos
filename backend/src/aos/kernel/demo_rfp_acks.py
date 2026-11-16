"""Demo-only: staggered supplier acks, Q&A, and proposals on RFP jobs (AOS_DEMO=1)."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from . import clock
from .org import OrgModel


def _demo_enabled() -> bool:
    return os.environ.get("AOS_DEMO", "0").strip().lower() in ("1", "true", "yes")


def _first_delay_seconds() -> float:
    raw = os.environ.get("AOS_DEMO_RFP_ACK_FIRST_S", "20").strip()
    try:
        return max(5.0, float(raw))
    except ValueError:
        return 20.0


def _stagger_seconds() -> float:
    raw = os.environ.get("AOS_DEMO_RFP_ACK_STAGGER_S", "25").strip()
    try:
        return max(5.0, float(raw))
    except ValueError:
        return 25.0


def _question_gap_seconds() -> float:
    raw = os.environ.get("AOS_DEMO_RFP_QUESTION_GAP_S", "28").strip()
    try:
        return max(8.0, float(raw))
    except ValueError:
        return 28.0


def _questions_per_supplier() -> int:
    raw = os.environ.get("AOS_DEMO_RFP_QUESTIONS_PER_VENDOR", "3").strip()
    try:
        n = int(raw)
    except ValueError:
        n = 3
    return max(2, min(3, n))


def _proposal_after_questions_seconds() -> float:
    raw = os.environ.get("AOS_DEMO_RFP_PROPOSAL_AFTER_Q_S", "35").strip()
    try:
        return max(10.0, float(raw))
    except ValueError:
        return 35.0


def _parse_iso(iso: str) -> datetime | None:
    try:
        text = iso.replace("Z", "+00:00") if iso.endswith("Z") else iso
        due = datetime.fromisoformat(text)
        if due.tzinfo is None:
            due = due.replace(tzinfo=UTC)
        return due
    except ValueError:
        return None


def build_demo_rfp_timeline(supplier_ids: list[str], *, anchor: datetime) -> list[dict[str, Any]]:
    """Ordered simulation events: ack, 2–3 questions, then full proposal per supplier."""
    first = _first_delay_seconds()
    stagger = _stagger_seconds()
    q_gap = _question_gap_seconds()
    q_count = _questions_per_supplier()
    proposal_gap = _proposal_after_questions_seconds()
    events: list[dict[str, Any]] = []
    for i, sid in enumerate(sorted(supplier_ids)):
        ack_at = anchor + timedelta(seconds=first + i * stagger)
        events.append({"id": f"{sid}:ack", "at": clock.iso_z(ack_at), "supplier": sid, "kind": "ack"})
        last_at = ack_at
        for q in range(1, q_count + 1):
            last_at = last_at + timedelta(seconds=q_gap)
            events.append(
                {
                    "id": f"{sid}:q{q}",
                    "at": clock.iso_z(last_at),
                    "supplier": sid,
                    "kind": "question",
                    "q": q,
                }
            )
        prop_at = last_at + timedelta(seconds=proposal_gap)
        events.append(
            {
                "id": f"{sid}:proposal",
                "at": clock.iso_z(prop_at),
                "supplier": sid,
                "kind": "proposal",
            }
        )
    events.sort(key=lambda e: e["at"])
    return events


async def schedule_demo_rfp_ack_times(
    conn: AsyncConnection,
    instance_id: str,
    supplier_ids: list[str],
    *,
    anchor: datetime | None = None,
) -> dict[str, str]:
    """Persist demo simulation timeline (ack + Q&A + proposal). Returns legacy ack map for tests."""
    if not supplier_ids:
        return {}
    when = anchor or clock.now()
    timeline = build_demo_rfp_timeline(supplier_ids, anchor=when)
    ack_map = {ev["supplier"]: ev["at"] for ev in timeline if ev["kind"] == "ack"}
    await conn.execute(
        "update work.instances set attributes = attributes || %s::jsonb where id = %s",
        (
            Jsonb(
                {
                    "demo_rfp_timeline": timeline,
                    "demo_rfp_timeline_done": [],
                    "demo_rfp_ack_due": ack_map,
                }
            ),
            instance_id,
        ),
    )
    return ack_map


async def _invited_supplier_ids(conn: AsyncConnection, instance_id: str) -> list[str]:
    cur = await conn.execute(
        "select key from work.artifacts"
        " where instance_id = %s and artifact_type = 'rfp_invitation' and coalesce(key, '') <> ''"
        " order by key",
        (instance_id,),
    )
    return [str(r[0]) for r in await cur.fetchall() if r[0]]


async def _load_timeline(conn: AsyncConnection, instance_id: str) -> tuple[list[dict[str, Any]], set[str]]:
    cur = await conn.execute("select attributes from work.instances where id = %s", (instance_id,))
    row = await cur.fetchone()
    if row is None:
        return [], set()
    attrs = row[0] if isinstance(row[0], dict) else json.loads(row[0] or "{}")
    timeline = attrs.get("demo_rfp_timeline")
    done_raw = attrs.get("demo_rfp_timeline_done") or []
    done = {str(x) for x in done_raw if x}
    if isinstance(timeline, list) and timeline:
        return [dict(e) for e in timeline if isinstance(e, dict)], done
    return [], done


async def _ensure_timeline(conn: AsyncConnection, instance_id: str) -> list[dict[str, Any]]:
    cur = await conn.execute(
        "select state, attributes, state_entered_at from work.instances where id = %s",
        (instance_id,),
    )
    row = await cur.fetchone()
    if row is None:
        return []
    state, attrs_raw, entered = row
    if str(state) != "awaiting_proposals":
        timeline, _ = await _load_timeline(conn, instance_id)
        return timeline
    attrs = attrs_raw if isinstance(attrs_raw, dict) else json.loads(attrs_raw or "{}")
    timeline = attrs.get("demo_rfp_timeline")
    if isinstance(timeline, list) and timeline:
        return [dict(e) for e in timeline if isinstance(e, dict)]
    supplier_ids = await _invited_supplier_ids(conn, instance_id)
    if not supplier_ids:
        return []
    anchor = entered if isinstance(entered, datetime) else clock.now()
    await schedule_demo_rfp_ack_times(conn, instance_id, supplier_ids, anchor=anchor)
    timeline, _ = await _load_timeline(conn, instance_id)
    return timeline


async def _mark_timeline_done(conn: AsyncConnection, instance_id: str, event_id: str, done: set[str]) -> None:
    done.add(event_id)
    await conn.execute(
        "update work.instances set attributes = attributes || %s::jsonb where id = %s",
        (Jsonb({"demo_rfp_timeline_done": sorted(done)}), instance_id),
    )


async def process_due_demo_rfp_acks(
    conn: AsyncConnection,
    org: OrgModel,
    instance_id: str,
    *,
    packs_dir: Path,
    demo: bool | None = None,
) -> int:
    """Run due demo timeline events (ack, questions with CM drafts, full proposal)."""
    if demo is None:
        demo = _demo_enabled()
    if not demo:
        return 0

    cur = await conn.execute("select state, org_id from work.instances where id = %s", (instance_id,))
    row = await cur.fetchone()
    if row is None or str(row[0]) != "awaiting_proposals":
        return 0
    org_id = str(row[1])

    timeline = await _ensure_timeline(conn, instance_id)
    if not timeline:
        return 0
    _, done = await _load_timeline(conn, instance_id)

    from aos.connectors.demo_proposal_fill import (
        build_demo_proposal_content,
        build_demo_question_content,
    )
    from aos.kernel import participants as participant_ops
    from aos.kernel import quote_capture
    from aos.kernel import quotes as quote_ops
    from aos.kernel import events as workflow_events

    buyer_id = await participant_ops.resolve_participant(
        conn, org, instance_id, "buyer", packs_dir=packs_dir
    )
    if buyer_id is None:
        return 0

    now = clock.now()
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    updated = 0
    now_iso = clock.iso_z(now)

    for ev in timeline:
        eid = str(ev.get("id") or "")
        if not eid or eid in done:
            continue
        due = _parse_iso(str(ev.get("at") or ""))
        if due is None or now < due:
            continue
        supplier_id = str(ev.get("supplier") or "")
        kind = str(ev.get("kind") or "")
        if not supplier_id:
            continue

        if kind == "ack":
            content = build_demo_proposal_content(supplier_id, "", received_at=now_iso, kind="ack")
        elif kind == "question":
            q = int(ev.get("q") or 1)
            content = build_demo_question_content(supplier_id, q, received_at=now_iso)
        elif kind == "proposal":
            body = "Please find our commercial proposal for the full redesign including CMS, API, and support."
            content = build_demo_proposal_content(supplier_id, body, received_at=now_iso, kind="proposal")
        else:
            continue

        existing = await quote_capture._latest_proposal_row(conn, instance_id, supplier_id)
        saved = await quote_capture._save_proposal_content(
            conn,
            instance_id=instance_id,
            supplier_id=supplier_id,
            content=content,
            buyer_id=buyer_id,
            existing=existing,
        )
        if saved:
            updated += 1
            from .demo_rfp_progress import post_supplier_sim_progress

            q_idx = int(ev.get("q") or 0) if kind == "question" else None
            await post_supplier_sim_progress(
                conn,
                org,
                org_id,
                instance_id,
                supplier_id=supplier_id,
                kind=kind,
                question_index=q_idx,
            )
            if kind == "question":
                from .demo_clarifications import open_clarification_pending

                row2 = await quote_capture._latest_proposal_row(conn, instance_id, supplier_id)
                if row2 is not None:
                    aid, ver, pcontent = row2
                    hcur = await conn.execute(
                        "select content_hash from work.artifact_versions where artifact_id = %s and version = %s",
                        (aid, ver),
                    )
                    hrow = await hcur.fetchone()
                    ch = str(hrow[0]) if hrow else ""
                    await open_clarification_pending(
                        conn,
                        org,
                        instance_id,
                        supplier_id=supplier_id,
                        question_index=q_idx or 1,
                        proposal_artifact_id=aid,
                        proposal_version=ver,
                        content_hash=ch,
                        proposal_content=pcontent,
                        packs_dir=packs_dir,
                    )
        await _mark_timeline_done(conn, instance_id, eid, done)

    if updated:
        await quote_ops.sync_proposal_count_attribute(conn, instance_id)
        await quote_ops.sync_ack_count_attribute(conn, instance_id)
        await workflow_events.evaluate_attribute_triggers(
            conn,
            org,
            instance_id,
            changed={"proposal_count", "ack_count"},
            packs_dir=packs_dir,
        )
    return updated


async def run_demo_rfp_ack_tick(
    pool: AsyncConnectionPool,
    *,
    org: OrgModel,
    packs_dir: Path,
    demo: bool,
) -> int:
    if not demo:
        return 0
    cur_sql = (
        "select id from work.instances"
        " where org_id = %s and status = 'running' and state = 'awaiting_proposals'"
        " order by state_entered_at"
    )
    async with pool.connection() as conn:
        cur = await conn.execute(cur_sql, (org.organization.id,))
        instance_ids = [str(r[0]) for r in await cur.fetchall()]
    total = 0
    for iid in instance_ids:
        async with pool.connection() as conn:
            async with conn.transaction():
                total += await process_due_demo_rfp_acks(
                    conn, org, iid, packs_dir=packs_dir, demo=demo
                )
    return total
