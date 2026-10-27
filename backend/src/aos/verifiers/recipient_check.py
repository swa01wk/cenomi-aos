"""recipient_check: each rfq_email was sent to the supplier address recorded on the draft."""

from __future__ import annotations

import json
from typing import Any

from psycopg import AsyncConnection


async def _rfq_emails(conn: AsyncConnection, instance_id: str) -> list[dict[str, Any]]:
    cur = await conn.execute(
        "select v.content from work.artifacts a"
        " join work.artifact_versions v on v.artifact_id = a.id and v.version = a.latest_version"
        " where a.instance_id = %s and a.artifact_type = 'rfq_email'",
        (instance_id,),
    )
    out: list[dict[str, Any]] = []
    for (raw,) in await cur.fetchall():
        content = raw if isinstance(raw, dict) else json.loads(raw or "{}")
        if isinstance(content, dict):
            out.append(content)
    return out


async def _sent_keys(conn: AsyncConnection, instance_id: str) -> set[str]:
    cur = await conn.execute("select attributes from work.instances where id = %s", (instance_id,))
    row = await cur.fetchone()
    if row is None:
        return set()
    attrs = row[0] if isinstance(row[0], dict) else json.loads(row[0] or "{}")
    keys = attrs.get("rfq_sent_keys") or []
    return {str(k) for k in keys if k}


async def verify(
    conn: AsyncConnection,
    gate: Any,
    result: dict[str, Any],
    defs: dict[str, dict[str, dict]],
) -> tuple[str, list[str]]:
    del result, defs
    emails = await _rfq_emails(conn, gate.instance_id)
    if not emails:
        return "FAIL", ["No rfq_email artifacts exist on this job."]
    sent = await _sent_keys(conn, gate.instance_id)
    findings: list[str] = []
    for content in emails:
        supplier_id = str(content.get("supplier_id") or "")
        to = str(content.get("to") or "").strip()
        key = f"{gate.instance_id}:rfq_send:{supplier_id}"
        if key not in sent:
            label = supplier_id or "unknown supplier"
            findings.append(f"RFQ for {label} was not sent (missing send receipt).")
        elif not to:
            findings.append(f"RFQ for {supplier_id} has no recipient address.")
    return ("FAIL", findings) if findings else ("PASS", [])
