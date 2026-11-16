"""Backfill Quick Quote client-demo artifacts and chat (QQ-0001, QQ-0013, etc.)."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

from psycopg import AsyncConnection

from aos.connectors.demo_qq_lines import (
    build_comparison_rows,
    build_line_matrix_rows,
    build_line_score_rows,
    build_qq_eval_artifacts,
    build_qq_rubric_artifacts,
    format_qq_eval_chat_block,
    format_qq_line_comparison_chat_block,
    pricing_lines_for,
    quote_total,
    resolve_three_suppliers,
)

from . import clock
from .conversation import insert_agent_turn, insert_person_turn, text_blocks
from .demo_artifact_upsert import artifact_row_sample, has_artifact, upsert_artifact
from .demo_pack_repin import align_instance_pack_to_seat
from .org import OrgModel


def _demo_enabled() -> bool:
    return os.environ.get("AOS_DEMO", "0").strip().lower() in ("1", "true", "yes")


async def _brief_quantity(conn: AsyncConnection, instance_id: str) -> int:
    cur = await conn.execute(
        "select v.content from work.artifacts a"
        " join work.artifact_versions v on v.artifact_id = a.id and v.version = a.latest_version"
        " where a.instance_id = %s and a.artifact_type = 'brief' limit 1",
        (instance_id,),
    )
    row = await cur.fetchone()
    if row is None:
        return 1
    content = row[0] if isinstance(row[0], dict) else {}
    try:
        return max(1, int(content.get("quantity") or 1))
    except (TypeError, ValueError):
        return 1


async def _existing_comparison_suppliers(conn: AsyncConnection, instance_id: str) -> list[str]:
    import json

    cur = await conn.execute(
        "select v.content from work.artifacts a"
        " join work.artifact_versions v on v.artifact_id = a.id and v.version = a.latest_version"
        " where a.instance_id = %s and a.artifact_type = 'comparison' limit 1",
        (instance_id,),
    )
    row = await cur.fetchone()
    if row is None:
        return []
    content = row[0] if isinstance(row[0], dict) else json.loads(row[0] or "{}")
    rows = content.get("rows")
    if not isinstance(rows, list):
        return []
    return [str(r["supplier"]) for r in rows if isinstance(r, dict) and r.get("supplier")]


async def _has_turn(conn: AsyncConnection, instance_id: str, needle: str) -> bool:
    cur = await conn.execute(
        "select 1 from work.turns where instance_id = %s and blocks::text like %s limit 1",
        (instance_id, f"%{needle}%"),
    )
    return await cur.fetchone() is not None


async def _ensure_participant(conn: AsyncConnection, instance_id: str, role: str, person_id: str) -> None:
    cur = await conn.execute(
        "select 1 from work.participants where instance_id = %s and role = %s limit 1",
        (instance_id, role),
    )
    if await cur.fetchone() is not None:
        return
    await conn.execute(
        "insert into work.participants (instance_id, role, person_id, bound_by)"
        " values (%s, %s, %s, 'rule')",
        (instance_id, role, person_id),
    )


async def heal_quick_quote_client_demo(
    conn: AsyncConnection,
    instance_id: str,
    *,
    org: OrgModel,
    packs_dir: Path,
) -> bool:
    _ = org, packs_dir
    if not _demo_enabled():
        return False
    cur = await conn.execute(
        "select workflow, state from work.instances where id = %s",
        (instance_id,),
    )
    row = await cur.fetchone()
    if row is None or str(row[0]) != "quick_quote":
        return False
    if str(row[1]) not in ("comparison", "ordering", "closed"):
        return False

    await align_instance_pack_to_seat(conn, org_id=org.organization.id, instance_id=instance_id)

    sample = await artifact_row_sample(conn, instance_id, "quote_evaluation")
    modern = sample is not None and "weighted_score" in sample
    sample_comm = await artifact_row_sample(conn, instance_id, "quote_eval_commercial")
    has_rubric = await has_artifact(conn, instance_id, "technical_criterion_scores")
    if modern and sample_comm is not None and has_rubric:
        return False

    await _ensure_participant(conn, instance_id, "category_manager", "rami")

    quantity = await _brief_quantity(conn, instance_id)
    keys = resolve_three_suppliers(await _existing_comparison_suppliers(conn, instance_id))

    await upsert_artifact(
        conn, instance_id, "quote_line_matrix", "", "Line comparison",
        {"rows": build_line_matrix_rows(keys, quantity=quantity)},
    )
    await upsert_artifact(
        conn, instance_id, "quote_line_scores", "", "Line scores",
        {"rows": build_line_score_rows(keys, quantity=quantity)},
    )
    commercial, technical, weighted = build_qq_eval_artifacts(keys, quantity=quantity)
    await upsert_artifact(
        conn, instance_id, "quote_eval_commercial", "", "Commercial evaluation", {"rows": commercial}
    )
    await upsert_artifact(
        conn, instance_id, "quote_eval_technical", "", "Technical evaluation", {"rows": technical}
    )
    await upsert_artifact(
        conn, instance_id, "quote_evaluation", "", "Weighted evaluation", {"rows": weighted}
    )
    tech_rub, comm_rub, policy = build_qq_rubric_artifacts(keys, quantity=quantity)
    await upsert_artifact(
        conn, instance_id, "technical_criterion_scores", "", "Technical rubric", {"rows": tech_rub}
    )
    await upsert_artifact(
        conn, instance_id, "commercial_criterion_scores", "", "Commercial rubric", {"rows": comm_rub}
    )
    await upsert_artifact(conn, instance_id, "eval_scoring_policy", "", "Scoring policy", policy)
    await upsert_artifact(
        conn, instance_id, "comparison", "", "Comparison",
        {"rows": build_comparison_rows(keys, quantity=quantity)},
    )

    now = clock.iso_z(datetime.now(UTC))
    for sid in keys:
        lines = pricing_lines_for(sid, quantity)
        total = quote_total(sid, quantity)
        await upsert_artifact(
            conn,
            instance_id,
            "quote",
            sid,
            f"Quote {sid}",
            {
                "supplier": sid,
                "unit_price": total / quantity,
                "total": total,
                "lead_time_days": 5 if sid == keys[0] else 7,
                "warranty_months": 12,
                "received_at": now,
                "pricing_lines": lines,
                "reply_excerpt": (
                    f"Quote for {quantity} unit(s): "
                    + ", ".join(f"{ln['line_id']} SAR {float(ln['amount']):,.0f}" for ln in lines)
                ),
                "notes": "Demo line-item quote.",
            },
        )

    roles_cur = await conn.execute(
        "select role from work.participants where instance_id = %s order by role",
        (instance_id,),
    )
    roles = [str(r[0]) for r in await roles_cur.fetchall()]

    if not await _has_turn(conn, instance_id, "Line-item comparison"):
        await insert_agent_turn(
            conn,
            instance_id=instance_id,
            seat_id="seat_sourcing_poc",
            seat_name="Noor Al-Rashid",
            blocks=text_blocks(format_qq_line_comparison_chat_block(keys, quantity=quantity)),
            audience_roles=roles,
            attempt_id=None,
        )
    if not await _has_turn(conn, instance_id, "Commercial eval"):
        await insert_agent_turn(
            conn,
            instance_id=instance_id,
            seat_id="seat_sourcing_poc",
            seat_name="Noor Al-Rashid",
            blocks=text_blocks(format_qq_eval_chat_block(keys, quantity=quantity)),
            audience_roles=roles,
            attempt_id=None,
        )
    if not await _has_turn(conn, instance_id, "commercial question"):
        await insert_agent_turn(
            conn,
            instance_id=instance_id,
            seat_id="seat_sourcing_poc",
            seat_name="Noor Al-Rashid",
            blocks=text_blocks(
                "**Najd Supplies** asked a **commercial** question (net-30 payment terms) — routed to **Noura**."
            ),
            audience_roles=roles,
            attempt_id=None,
        )
        await insert_person_turn(
            conn,
            instance_id=instance_id,
            person_id="noura",
            text="Answered **commercial** quote clarification for Najd (standard Cenomi net-30).",
            client_turn_id=f"demo-qq-comm-{instance_id}",
            audience_roles=roles,
        )
    if not await _has_turn(conn, instance_id, "technical question"):
        await insert_agent_turn(
            conn,
            instance_id=instance_id,
            seat_id="seat_sourcing_poc",
            seat_name="Noor Al-Rashid",
            blocks=text_blocks(
                "**Webknot** asked a **technical** question (MDM enrollment spec) — routed to **Rami**."
            ),
            audience_roles=roles,
            attempt_id=None,
        )
        await insert_person_turn(
            conn,
            instance_id=instance_id,
            person_id="rami",
            text="Answered **technical** quote clarification for Webknot (MDM profile per facilities standard).",
            client_turn_id=f"demo-qq-tech-{instance_id}",
            audience_roles=roles,
        )
    if not await _has_turn(conn, instance_id, "line-item BAFO"):
        await insert_person_turn(
            conn,
            instance_id=instance_id,
            person_id="noura",
            text=(
                "Challenged **line-item** outliers in the thread (device line vs peer median) before award — "
                "same BAFO pattern as the web RFP module negotiation."
            ),
            client_turn_id=f"demo-qq-bafo-{instance_id}",
            audience_roles=roles,
        )

    return True
