"""Progress turn when a job closes with a purchase order placed (demo polish)."""

from __future__ import annotations

import json
import re
from typing import Any

from psycopg import AsyncConnection

from .org import OrgModel
from .progress import post_agent_progress_turn, text_blocks


def _money_display(raw: Any) -> str:
    if raw is None:
        return ""
    if isinstance(raw, dict) and "amount" in raw:
        amt = raw.get("amount")
        cur = raw.get("currency") or "SAR"
        try:
            n = float(amt)
            return f"{cur} {n:,.2f}"
        except (TypeError, ValueError):
            return f"{cur} {amt}"
    try:
        return f"SAR {float(raw):,.2f}"
    except (TypeError, ValueError):
        return str(raw)


async def _load_po_payload(conn: AsyncConnection, instance_id: str) -> dict[str, Any] | None:
    cur = await conn.execute(
        "select v.content from work.artifacts a"
        " join work.artifact_versions v on v.artifact_id = a.id and v.version = a.latest_version"
        " where a.instance_id = %s and a.artifact_type = 'po_payload' and a.latest_version >= 1"
        " order by v.created_at desc limit 1",
        (instance_id,),
    )
    row = await cur.fetchone()
    if row is None:
        return None
    content = row[0] if isinstance(row[0], dict) else json.loads(row[0] or "{}")
    return content if isinstance(content, dict) else None


async def _already_announced(conn: AsyncConnection, instance_id: str, po_ref: str) -> bool:
    cur = await conn.execute(
        "select blocks from work.turns where instance_id = %s and author_kind = 'seat'"
        " order by seq desc limit 40",
        (instance_id,),
    )
    needle = po_ref.lower()
    for (blocks,) in await cur.fetchall():
        raw = blocks if isinstance(blocks, list) else json.loads(blocks or "[]")
        for block in raw:
            if not isinstance(block, dict):
                continue
            text = str(block.get("text") or "")
            if "purchase order" in text.lower() and needle in text.lower():
                return True
    return False


def _display_po_id(reference: str, instance_id: str) -> str:
    ref = reference.strip()
    if ref:
        return ref
    suffix = re.sub(r"[^0-9]", "", instance_id) or "0"
    return f"PO-{suffix.zfill(6)}"


async def post_po_ordered_announcement_if_needed(
    conn: AsyncConnection,
    *,
    org: OrgModel,
    org_id: str,
    instance_id: str,
) -> bool:
    """One seat progress turn: PO created in ERP (idempotent per reference)."""
    icur = await conn.execute(
        "select seat, seat_version, status from work.instances where id = %s",
        (instance_id,),
    )
    inst = await icur.fetchone()
    if inst is None or str(inst[2]) != "closed":
        return False
    payload = await _load_po_payload(conn, instance_id)
    if payload is None:
        return False

    po_ref = _display_po_id(str(payload.get("reference") or ""), instance_id)
    if await _already_announced(conn, instance_id, po_ref):
        return False

    supplier = str(payload.get("supplier_id") or "the awarded supplier").strip()
    amount = _money_display(payload.get("po_amount"))
    ship = str(payload.get("ship_to") or "").strip()
    ship_bit = f" Ship-to: {ship}." if ship else ""

    lines = [
        f"Purchase order {po_ref} has been created in Oracle Fusion Procurement for supplier {supplier}.",
    ]
    if amount:
        lines.append(f"Order total: {amount}.")
    if ship_bit:
        lines.append(ship_bit.strip())
    lines.append("The order is placed — procurement can track it in the ERP.")

    seat_name, seat_version = str(inst[0]), int(inst[1])
    await post_agent_progress_turn(
        conn,
        org=org,
        org_id=org_id,
        instance_id=instance_id,
        seat_name=seat_name,
        seat_version=seat_version,
        blocks=text_blocks("\n".join(lines)),
        audience={"roles": ["buyer", "requester", "procurement_approver"]},
    )
    return True
