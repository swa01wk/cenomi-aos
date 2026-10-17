"""Audit chain persistence (ADR 008).

``record`` appends under a row lock on the organization's chain head, so concurrent kernel writers
serialize and sequence numbers stay gap-free. Call it inside the same transaction as the change it
describes: if the change rolls back, so does its audit record.
"""

from __future__ import annotations

import json
from datetime import timezone

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from . import audit


class ChainMissing(Exception):
    pass


def _jsonable(data: dict | None) -> dict:
    # Hash exactly what Postgres will hand back: plain JSON types only.
    return json.loads(json.dumps(data or {}, default=str))


async def record(conn: AsyncConnection, *, org_id: str, actor: str, action: str, subject: str,
                 correlation_id: str | None = None, data: dict | None = None) -> audit.AuditRecord:
    cur = await conn.execute(
        "select last_seq, last_hash from evidence.audit_heads where org_id = %s for update", (org_id,))
    head = await cur.fetchone()
    if head is None:
        raise ChainMissing(f"no audit chain for organization {org_id!r}; seed the organization first")
    rec = audit.append(head[0], head[1], org_id=org_id, actor=actor, action=action, subject=subject,
                       correlation_id=correlation_id, data=_jsonable(data))
    await conn.execute(
        "insert into evidence.audit_events (org_id, seq, occurred_at, actor, action, subject, correlation_id, data,"
        " prev_hash, record_hash) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (rec.org_id, rec.seq, rec.occurred_at, rec.actor, rec.action, rec.subject, rec.correlation_id,
         Jsonb(rec.data), rec.prev_hash, rec.record_hash))
    await conn.execute("update evidence.audit_heads set last_seq = %s, last_hash = %s where org_id = %s",
                       (rec.seq, rec.record_hash, org_id))
    return rec


_COLUMNS = "org_id, seq, occurred_at, actor, action, subject, correlation_id, data, prev_hash, record_hash"


def _row(r) -> audit.AuditRecord:
    occurred = r[2].astimezone(timezone.utc).isoformat(timespec="seconds")
    return audit.AuditRecord(r[0], r[1], occurred, r[3], r[4], r[5], r[6], r[7], r[8], r[9])


async def page(conn: AsyncConnection, org_id: str, *, limit: int = 50, before_seq: int | None = None,
               correlation_id: str | None = None) -> list[audit.AuditRecord]:
    """Newest first."""
    sql = f"select {_COLUMNS} from evidence.audit_events where org_id = %s"
    args: list = [org_id]
    if before_seq is not None:
        sql += " and seq < %s"
        args.append(before_seq)
    if correlation_id is not None:
        sql += " and correlation_id = %s"
        args.append(correlation_id)
    sql += " order by seq desc limit %s"
    args.append(limit)
    cur = await conn.execute(sql, args)
    return [_row(r) for r in await cur.fetchall()]


async def verify_chain(conn: AsyncConnection, org_id: str) -> audit.ChainReport:
    cur = await conn.execute(f"select {_COLUMNS} from evidence.audit_events where org_id = %s order by seq", (org_id,))
    report = audit.verify([_row(r) for r in await cur.fetchall()])
    head = await (await conn.execute("select last_seq, last_hash from evidence.audit_heads where org_id = %s",
                                     (org_id,))).fetchone()
    if report.intact and head and (head[0] != report.records or head[1] != report.head_hash):
        return audit.ChainReport(False, report.records, report.head_hash, head[0],
                                 "chain head does not match the last record (records removed from the end)")
    return report
