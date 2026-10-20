"""Demo clock and DemoState reads (AOS_DEMO=1)."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from typing import Any

from psycopg import AsyncConnection

from . import audit_store, clock


async def read_offset_seconds(conn: AsyncConnection, org_id: str) -> int:
    cur = await conn.execute(
        "select offset_seconds from work.demo_clock where org_id = %s",
        (org_id,),
    )
    row = await cur.fetchone()
    return int(row[0]) if row else 0


async def ensure_demo_clock_row(conn: AsyncConnection, org_id: str) -> None:
    await conn.execute(
        "insert into work.demo_clock (org_id, offset_seconds) values (%s, 0)"
        " on conflict (org_id) do nothing",
        (org_id,),
    )


async def load_demo_clock(conn: AsyncConnection, org_id: str) -> int:
    await ensure_demo_clock_row(conn, org_id)
    offset = await read_offset_seconds(conn, org_id)
    clock.set_offset(offset)
    return offset


async def build_demo_state(conn: AsyncConnection, org_id: str) -> dict[str, Any]:
    cur = await conn.execute(
        "select t.instance_id, t.name, t.fires_at"
        " from work.timers t"
        " join work.instances i on i.id = t.instance_id"
        " where i.org_id = %s and t.status = 'scheduled'"
        " order by t.fires_at, t.instance_id, t.name",
        (org_id,),
    )
    timer_rows = await cur.fetchall()
    return {
        "now": clock.iso_z(clock.now()),
        "timers": [
            {
                "instance_id": str(inst_id),
                "timer": str(name),
                "fires_at": clock.iso_z(_as_utc(fires_at)),
            }
            for inst_id, name, fires_at in timer_rows
        ],
        "faults": {},
    }


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


async def advance_demo_clock(
    conn: AsyncConnection,
    org_id: str,
    *,
    minutes: int | None = None,
    to_next_timer: bool = False,
) -> int:
    await ensure_demo_clock_row(conn, org_id)
    cur = await conn.execute(
        "select offset_seconds from work.demo_clock where org_id = %s for update",
        (org_id,),
    )
    row = await cur.fetchone()
    offset = int(row[0]) if row else 0
    audit_data: dict[str, Any] = {}

    if minutes is not None:
        offset += minutes * 60
        audit_data = {"minutes": minutes, "offset_seconds": offset}
    elif to_next_timer:
        kernel_now = clock.wall_now() + timedelta(seconds=offset)
        cur = await conn.execute(
            "select min(t.fires_at)"
            " from work.timers t"
            " join work.instances i on i.id = t.instance_id"
            " where i.org_id = %s and t.status = 'scheduled' and t.fires_at > %s",
            (org_id, kernel_now),
        )
        nxt = await cur.fetchone()
        if nxt and nxt[0] is not None:
            target = _as_utc(nxt[0])
            # Round up: truncating would leave kernel now() a fraction of a second before fires_at,
            # and the tick only fires timers with fires_at <= now().
            offset = math.ceil((target - clock.wall_now()).total_seconds())
            audit_data = {"to_next_timer": True, "offset_seconds": offset}
        else:
            audit_data = {"to_next_timer": True, "offset_seconds": offset}
    else:
        raise ValueError("advance body must set minutes or to_next_timer")

    await conn.execute(
        "update work.demo_clock set offset_seconds = %s, updated_at = now() where org_id = %s",
        (offset, org_id),
    )
    await audit_store.record(
        conn,
        org_id=org_id,
        actor="demo",
        action="demo.clock_advanced",
        subject="demo-clock",
        data=audit_data,
    )
    return offset
