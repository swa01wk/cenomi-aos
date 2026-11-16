"""Shared demo artifact upsert helpers."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from . import ids


def content_hash(content: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(content, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


async def upsert_artifact(
    conn: AsyncConnection,
    instance_id: str,
    artifact_type: str,
    key: str,
    name: str,
    content: dict[str, Any],
    *,
    status: str = "final",
) -> None:
    cur = await conn.execute(
        "select id, latest_version from work.artifacts"
        " where instance_id = %s and artifact_type = %s and key = %s limit 1",
        (instance_id, artifact_type, key),
    )
    row = await cur.fetchone()
    ch = content_hash(content)
    if row is None:
        aid = ids.new_artifact_id()
        await conn.execute(
            "insert into work.artifacts (id, instance_id, artifact_type, key, name, status, latest_version)"
            " values (%s, %s, %s, %s, %s, %s, 1)",
            (aid, instance_id, artifact_type, key, name, status),
        )
        await conn.execute(
            "insert into work.artifact_versions (artifact_id, version, content, content_hash,"
            " produced_by_kind, produced_by, inputs, sources)"
            " values (%s, 1, %s, %s, 'person', 'noura', '[]'::jsonb, '[]'::jsonb)",
            (aid, Jsonb(content), ch),
        )
        return
    aid, ver = row[0], int(row[1]) + 1
    await conn.execute(
        "insert into work.artifact_versions (artifact_id, version, content, content_hash,"
        " produced_by_kind, produced_by, inputs, sources)"
        " values (%s, %s, %s, %s, 'person', 'noura', '[]'::jsonb, '[]'::jsonb)",
        (aid, ver, Jsonb(content), ch),
    )
    await conn.execute(
        "update work.artifacts set latest_version = %s, status = %s where id = %s",
        (ver, status, aid),
    )


async def has_artifact(conn: AsyncConnection, instance_id: str, artifact_type: str) -> bool:
    cur = await conn.execute(
        "select 1 from work.artifacts where instance_id = %s and artifact_type = %s limit 1",
        (instance_id, artifact_type),
    )
    return await cur.fetchone() is not None


async def artifact_row_sample(
    conn: AsyncConnection,
    instance_id: str,
    artifact_type: str,
) -> dict | None:
    import json

    cur = await conn.execute(
        "select v.content from work.artifacts a"
        " join work.artifact_versions v on v.artifact_id = a.id and v.version = a.latest_version"
        " where a.instance_id = %s and a.artifact_type = %s limit 1",
        (instance_id, artifact_type),
    )
    row = await cur.fetchone()
    if row is None:
        return None
    content = row[0] if isinstance(row[0], dict) else json.loads(row[0] or "{}")
    rows = content.get("rows") if isinstance(content, dict) else None
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
        return None
    return rows[0]
