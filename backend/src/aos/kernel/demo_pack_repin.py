"""Demo: point job pack pins at the seat's published pack so new artifact views apply."""

from __future__ import annotations

import os

from psycopg import AsyncConnection


def demo_enabled() -> bool:
    return os.environ.get("AOS_DEMO", "0").strip().lower() in ("1", "true", "yes")


async def align_instance_pack_to_seat(conn: AsyncConnection, *, org_id: str, instance_id: str) -> bool:
    if not demo_enabled():
        return False
    cur = await conn.execute(
        "select seat, seat_version, pack_version_id from work.instances where id = %s and org_id = %s",
        (instance_id, org_id),
    )
    row = await cur.fetchone()
    if row is None:
        return False
    seat_name, seat_version, pvid = str(row[0]), int(row[1]), str(row[2])
    scur = await conn.execute(
        "select pack_version_id from registry.seats where org_id = %s and name = %s and version = %s",
        (org_id, seat_name, seat_version),
    )
    srow = await scur.fetchone()
    if srow is None:
        return False
    seat_pvid = str(srow[0])
    if seat_pvid == pvid:
        return False
    await conn.execute(
        "update work.instances set pack_version_id = %s where id = %s",
        (seat_pvid, instance_id),
    )
    return True
