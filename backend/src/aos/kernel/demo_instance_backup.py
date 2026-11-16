"""Export and restore a job snapshot for demo backup (AOS_DEMO=1)."""

from __future__ import annotations

import json
from typing import Any

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb


async def export_instance(conn: AsyncConnection, instance_id: str) -> dict[str, Any]:
    cur = await conn.execute("select * from work.instances where id = %s", (instance_id,))
    inst_row = await cur.fetchone()
    if inst_row is None:
        raise ValueError(f"instance {instance_id!r} not found")
    cols = [d.name for d in cur.description]
    instance = dict(zip(cols, inst_row, strict=True))
    for k, v in list(instance.items()):
        if hasattr(v, "isoformat"):
            instance[k] = v.isoformat()

    async def _rows(sql: str, *args: object) -> list[dict[str, Any]]:
        c = await conn.execute(sql, args)
        if c.description is None:
            return []
        names = [d.name for d in c.description]
        out: list[dict[str, Any]] = []
        for row in await c.fetchall():
            item = dict(zip(names, row, strict=True))
            for key, val in list(item.items()):
                if hasattr(val, "isoformat"):
                    item[key] = val.isoformat()
            out.append(item)
        return out

    return {
        "format": "aos_demo_instance_v1",
        "instance": instance,
        "participants": await _rows(
            "select * from work.participants where instance_id = %s order by role", instance_id
        ),
        "artifacts": await _rows(
            "select * from work.artifacts where instance_id = %s order by id", instance_id
        ),
        "artifact_versions": await _rows(
            "select v.* from work.artifact_versions v"
            " join work.artifacts a on a.id = v.artifact_id"
            " where a.instance_id = %s order by v.artifact_id, v.version",
            instance_id,
        ),
        "turns": await _rows(
            "select * from work.turns where instance_id = %s order by seq", instance_id
        ),
        "pending_items": await _rows(
            "select * from work.pending_items where instance_id = %s order by created_at", instance_id
        ),
        "timers": await _rows("select * from work.timers where instance_id = %s order by id", instance_id),
        "tasks": await _rows(
            "select * from work.tasks where instance_id = %s order by created_at", instance_id
        ),
    }


async def _delete_instance_tree(conn: AsyncConnection, instance_id: str) -> None:
    await conn.execute(
        "delete from work.artifact_versions where artifact_id in"
        " (select id from work.artifacts where instance_id = %s)",
        (instance_id,),
    )
    await conn.execute(
        "delete from work.attempts where task_id in (select id from work.tasks where instance_id = %s)",
        (instance_id,),
    )
    for table in (
        "work.pending_items",
        "work.turns",
        "work.tasks",
        "work.timers",
        "work.participants",
        "work.artifacts",
        "work.regions",
        "work.instance_transitions",
        "work.instance_shared_attachments",
        "work.inbound_messages",
    ):
        await conn.execute(f"delete from {table} where instance_id = %s", (instance_id,))
    await conn.execute("delete from work.instances where id = %s", (instance_id,))


async def restore_instance(conn: AsyncConnection, payload: dict[str, Any], *, replace: bool = True) -> str:
    if payload.get("format") != "aos_demo_instance_v1":
        raise ValueError("unsupported backup format")
    inst = payload["instance"]
    iid = str(inst["id"])
    if replace:
        await _delete_instance_tree(conn, iid)

    inst_cols = [
        "id",
        "org_id",
        "workflow",
        "pack_version_id",
        "seat",
        "seat_version",
        "title",
        "state",
        "status",
        "attributes",
        "correlation_id",
        "version",
        "created_by",
        "idempotency_key",
        "created_at",
        "state_entered_at",
        "closed_at",
        "raised_events",
    ]
    row = {k: inst.get(k) for k in inst_cols}
    placeholders = ", ".join(f"%({k})s" for k in inst_cols)
    await conn.execute(
        f"insert into work.instances ({', '.join(inst_cols)}) values ({placeholders})",
        row,
    )

    for table, rows, col_map in (
        ("work.participants", payload.get("participants") or [], None),
        ("work.artifacts", payload.get("artifacts") or [], None),
        ("work.artifact_versions", payload.get("artifact_versions") or [], None),
        ("work.turns", payload.get("turns") or [], None),
        ("work.pending_items", payload.get("pending_items") or [], None),
        ("work.timers", payload.get("timers") or [], None),
        ("work.tasks", payload.get("tasks") or [], None),
    ):
        if not rows:
            continue
        for r in rows:
            keys = list(r.keys())
            sql = f"insert into {table} ({', '.join(keys)}) values ({', '.join('%s' for _ in keys)})"
            vals = [Jsonb(v) if isinstance(v, dict) else v for v in (r[k] for k in keys)]
            await conn.execute(sql, vals)
    return iid
