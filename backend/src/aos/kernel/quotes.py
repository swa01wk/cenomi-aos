"""Quote capture helpers (POC)."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from . import clock, ids


async def sync_proposal_count_attribute(conn: AsyncConnection, instance_id: str) -> int:
    """Set attr.proposal_count to distinct suppliers with at least one saved proposal version."""
    cur = await conn.execute(
        """
        select count(*) from (
          select distinct coalesce(
            nullif(trim(a.key), ''),
            nullif(trim(v.content->>'supplier_id'), ''),
            nullif(trim(v.content->>'supplier'), ''),
            a.id::text
          ) as supplier_key
          from work.artifacts a
          join work.artifact_versions v on v.artifact_id = a.id and v.version = a.latest_version
          where a.instance_id = %s and a.artifact_type = 'proposal' and a.latest_version >= 1
        ) q
        where supplier_key is not null and supplier_key <> ''
        """,
        (instance_id,),
    )
    row = await cur.fetchone()
    count = int(row[0]) if row else 0
    await conn.execute(
        "update work.instances set attributes = attributes || %s::jsonb where id = %s",
        (Jsonb({"proposal_count": count}), instance_id),
    )
    return count


async def sync_quote_count_attribute(conn: AsyncConnection, instance_id: str) -> int:
    """Set attr.quote_count to distinct suppliers with at least one saved quote version."""
    cur = await conn.execute(
        """
        select count(*) from (
          select distinct coalesce(
            nullif(trim(a.key), ''),
            nullif(trim(v.content->>'supplier_id'), ''),
            nullif(trim(v.content->>'supplier'), ''),
            a.id::text
          ) as supplier_key
          from work.artifacts a
          join work.artifact_versions v on v.artifact_id = a.id and v.version = a.latest_version
          where a.instance_id = %s and a.artifact_type = 'quote' and a.latest_version >= 1
        ) q
        where supplier_key is not null and supplier_key <> ''
        """,
        (instance_id,),
    )
    row = await cur.fetchone()
    count = int(row[0]) if row else 0
    await conn.execute(
        "update work.instances set attributes = attributes || %s::jsonb where id = %s",
        (Jsonb({"quote_count": count}), instance_id),
    )
    return count


async def _reply_window_duration(conn: AsyncConnection, instance_id: str) -> str:
    from .reply_deadline import brief_reply_duration_for_instance

    return await brief_reply_duration_for_instance(conn, instance_id)


async def _schedule_quote_deadline_timer(
    conn: AsyncConnection,
    instance_id: str,
    *,
    update_attrs: bool,
) -> Any:
    duration = clock.parse_duration(await _reply_window_duration(conn, instance_id))
    fires_at = clock.now() + duration
    fires_iso = clock.iso_z(fires_at)

    if update_attrs:
        cur = await conn.execute(
            "select attributes from work.instances where id = %s for update",
            (instance_id,),
        )
        row = await cur.fetchone()
        attrs = row[0] if row and isinstance(row[0], dict) else json.loads(row[0] or "{}") if row else {}
        attrs = {**attrs, "quote_deadline_at": fires_iso}
        await conn.execute(
            "update work.instances set attributes = %s where id = %s",
            (Jsonb(attrs), instance_id),
        )

    await conn.execute(
        "update work.timers set status = 'cancelled'"
        " where instance_id = %s and name = 'quote_deadline' and status = 'scheduled'",
        (instance_id,),
    )
    cur = await conn.execute(
        "select coalesce(max(generation), 0) from work.timers where instance_id = %s and name = 'quote_deadline'",
        (instance_id,),
    )
    gen_row = await cur.fetchone()
    generation = int(gen_row[0]) + 1 if gen_row else 1
    await conn.execute(
        "insert into work.timers (id, instance_id, name, emits, fires_at, generation)"
        " values (%s, %s, 'quote_deadline', 'quotes_closed', %s, %s)",
        (ids.new_timer_id(), instance_id, fires_at, generation),
    )
    return fires_at


async def ensure_quote_deadline_from_brief(conn: AsyncConnection, instance_id: str) -> None:
    """Fix jobs that still carry the pack default (e.g. 5d) instead of the brief reply window."""
    duration = clock.parse_duration(await _reply_window_duration(conn, instance_id))
    slack = timedelta(seconds=120)
    cur = await conn.execute(
        "select fires_at from work.timers"
        " where instance_id = %s and name = 'quote_deadline' and status = 'scheduled'"
        " order by generation desc limit 1",
        (instance_id,),
    )
    row = await cur.fetchone()
    if row is None or row[0] is None:
        await _schedule_quote_deadline_timer(conn, instance_id, update_attrs=True)
        return
    fires_at = row[0]
    if fires_at.tzinfo is None:
        from datetime import UTC

        fires_at = fires_at.replace(tzinfo=UTC)
    remaining = fires_at - clock.now()
    if remaining > duration + slack:
        await _schedule_quote_deadline_timer(conn, instance_id, update_attrs=True)


async def restart_reply_deadlines(
    conn: AsyncConnection,
    *,
    instance_id: str,
    supplier_ids: list[str],
) -> dict[str, str]:
    """After resend, restart the quote window for the given suppliers (and extend the job timer)."""
    if not supplier_ids:
        return {}
    fires_at = await _schedule_quote_deadline_timer(conn, instance_id, update_attrs=False)
    fires_iso = clock.iso_z(fires_at)

    cur = await conn.execute(
        "select attributes from work.instances where id = %s for update",
        (instance_id,),
    )
    row = await cur.fetchone()
    attrs = row[0] if row and isinstance(row[0], dict) else json.loads(row[0] or "{}") if row else {}
    by_supplier = dict(attrs.get("quote_resend_deadlines") or {})
    for sid in supplier_ids:
        by_supplier[str(sid)] = fires_iso
    attrs = {**attrs, "quote_resend_deadlines": by_supplier, "quote_deadline_at": fires_iso}
    await conn.execute(
        "update work.instances set attributes = %s where id = %s",
        (Jsonb(attrs), instance_id),
    )
    return {str(sid): fires_iso for sid in supplier_ids}


async def quote_timer_for_snapshot(conn: AsyncConnection, instance_id: str) -> dict[str, Any]:
    cur = await conn.execute(
        "select fires_at from work.timers"
        " where instance_id = %s and name = 'quote_deadline' and status = 'scheduled'"
        " order by generation desc limit 1",
        (instance_id,),
    )
    row = await cur.fetchone()
    out: dict[str, Any] = {}
    if row and row[0] is not None:
        dt = row[0]
        out["quote_deadline_at"] = dt.isoformat() if hasattr(dt, "isoformat") else str(dt)
    acur = await conn.execute("select attributes from work.instances where id = %s", (instance_id,))
    arow = await acur.fetchone()
    if arow:
        attrs = arow[0] if isinstance(arow[0], dict) else json.loads(arow[0] or "{}")
        if isinstance(attrs.get("quote_resend_deadlines"), dict):
            out["quote_resend_deadlines"] = attrs["quote_resend_deadlines"]
    return out
