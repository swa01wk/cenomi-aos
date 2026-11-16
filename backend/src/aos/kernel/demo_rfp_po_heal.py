"""Demo: after RFP award, seed po_payload when rfp_po_create worker did not finish."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from aos.connectors.demo_proposal_fill import (
    _DEMO_BY_SUPPLIER,
    demo_supplier_display_name,
    demo_supplier_id_from_display_name,
)

from . import ids
from .org import OrgModel


def _hash(content: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(content, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


async def _awarded_supplier_name(conn: AsyncConnection, instance_id: str) -> str | None:
    cur = await conn.execute(
        "select selection from gov.decision_records"
        " where subject_kind = 'instance' and subject_id = %s"
        " and event in ('decision.vendor_recommended', 'decision.supplier_selected')"
        " order by at desc limit 1",
        (instance_id,),
    )
    row = await cur.fetchone()
    if row is None or not row[0]:
        return None
    sel = row[0] if isinstance(row[0], list) else json.loads(row[0] or "[]")
    if not isinstance(sel, list) or not sel:
        return None
    raw = str(sel[0]).strip()
    if raw.upper().startswith("SUP-"):
        return demo_supplier_display_name(raw)
    return raw or None


async def _proposal_total(conn: AsyncConnection, instance_id: str, supplier_id: str) -> float | None:
    cur = await conn.execute(
        "select v.content from work.artifacts a"
        " join work.artifact_versions v on v.artifact_id = a.id and v.version = a.latest_version"
        " where a.instance_id = %s and a.artifact_type = 'proposal' and a.key = %s limit 1",
        (instance_id, supplier_id),
    )
    row = await cur.fetchone()
    if row is None:
        return None
    content = row[0] if isinstance(row[0], dict) else json.loads(row[0] or "{}")
    total = content.get("total")
    if total is None:
        return None
    try:
        return float(total)
    except (TypeError, ValueError):
        return None


async def _brief_ship_to(conn: AsyncConnection, instance_id: str) -> str:
    cur = await conn.execute(
        "select v.content from work.artifacts a"
        " join work.artifact_versions v on v.artifact_id = a.id and v.version = a.latest_version"
        " where a.instance_id = %s and a.artifact_type = 'brief' limit 1",
        (instance_id,),
    )
    row = await cur.fetchone()
    if row is None:
        return "Saudi Arabia"
    content = row[0] if isinstance(row[0], dict) else json.loads(row[0] or "{}")
    site = str(content.get("delivery_site") or "").strip()
    return site or "Saudi Arabia"


def _po_payload(
    *,
    instance_id: str,
    supplier_id: str,
    total: float,
    ship_to: str,
    need_by: str = "2027-05-02",
) -> dict[str, Any]:
    name = demo_supplier_display_name(supplier_id)
    return {
        "supplier_id": supplier_id,
        "ship_to": ship_to,
        "need_by": need_by,
        "currency": "SAR",
        "reference": f"AOS-{instance_id}-PR1",
        "lines": [
            {
                "item": "Cenomi Malls public website redesign — CMS, REST API, bilingual delivery (RFP award)",
                "quantity": 1,
                "unit_price": total,
            }
        ],
        "po_amount": {"amount": total, "currency": "SAR"},
        "notes": f"Awarded to {name} per rfp_evaluation.",
    }


async def heal_rfp_demo_po_payload(
    conn: AsyncConnection,
    instance_id: str,
    *,
    org: OrgModel,
    packs_dir: Any,
) -> bool:
    """Insert po_payload after award when ordering is stuck without one (demo reliability)."""
    _ = org, packs_dir
    cur = await conn.execute(
        "select workflow, state, status from work.instances where id = %s",
        (instance_id,),
    )
    row = await cur.fetchone()
    if row is None or str(row[0]) != "sourcing_rfp" or str(row[1]) != "ordering" or str(row[2]) != "running":
        return False
    pcur = await conn.execute(
        "select 1 from work.artifacts where instance_id = %s and artifact_type = 'po_payload' and latest_version >= 1",
        (instance_id,),
    )
    if await pcur.fetchone() is not None:
        return False

    supplier_name = await _awarded_supplier_name(conn, instance_id)
    if not supplier_name:
        return False
    supplier_id = demo_supplier_id_from_display_name(supplier_name)
    if supplier_id is None:
        return False
    total = await _proposal_total(conn, instance_id, supplier_id)
    if total is None:
        total = float(_DEMO_BY_SUPPLIER.get(supplier_id, ("", 4_620_000, 280, 12))[1])

    ship_to = await _brief_ship_to(conn, instance_id)
    content = _po_payload(instance_id=instance_id, supplier_id=supplier_id, total=total, ship_to=ship_to)
    aid = ids.new_artifact_id()
    ch = _hash(content)
    await conn.execute(
        "insert into work.artifacts (id, instance_id, artifact_type, key, name, status, latest_version)"
        " values (%s, %s, 'po_payload', '', 'PO', 'draft', 1)",
        (aid, instance_id),
    )
    await conn.execute(
        "insert into work.artifact_versions (artifact_id, version, content, content_hash,"
        " produced_by_kind, produced_by, inputs, sources)"
        " values (%s, 1, %s, %s, 'person', 'noura', '[]'::jsonb, '[]'::jsonb)",
        (aid, Jsonb(content), ch),
    )
    return True
