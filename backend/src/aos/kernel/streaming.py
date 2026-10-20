"""Outbox cursor rules, visibility and UiEvent projection for SSE (M1-BE-04 B)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from psycopg import AsyncConnection

from . import ids
from .conversation import turn_visible


@dataclass(frozen=True)
class CursorValidation:
    ok: bool
    stream: str | None = None
    seq: int = 0
    reason: str | None = None  # SnapshotRequired reason when not ok


def outbox_visible(audience: dict[str, Any], *, person_id: str, participant_roles: list[str]) -> bool:
    if "person_id" in audience:
        return audience["person_id"] == person_id
    roles = audience.get("roles")
    if roles is not None:
        return turn_visible(list(roles), participant_roles)
    return True


def outbox_row_to_ui_event(
    *,
    stream: str,
    seq: int,
    event_type: str,
    instance_id: str | None,
    data: dict[str, Any],
    created_at: datetime,
) -> dict[str, Any]:
    at = created_at.isoformat() if hasattr(created_at, "isoformat") else str(created_at)
    doc: dict[str, Any] = {
        "id": ids.ui_event_cursor(stream, seq),
        "type": event_type,
        "at": at,
        "data": data,
    }
    if instance_id is not None:
        doc["instance_id"] = instance_id
    return doc


def snapshot_required_event(
    *,
    stream: str,
    seq: int,
    reason: str,
    instance_id: str | None = None,
    at: str | None = None,
) -> dict[str, Any]:
    when = at or datetime.now(timezone.utc).isoformat()
    doc: dict[str, Any] = {
        "id": ids.ui_event_cursor(stream, seq),
        "type": "snapshot.required",
        "at": when,
        "data": {"reason": reason},
    }
    if instance_id is not None:
        doc["instance_id"] = instance_id
    return doc


def message_delta_event(
    *,
    instance_id: str,
    turn_id: str,
    delta_seq: int,
    text: str,
) -> dict[str, Any]:
    """Ephemeral delta; JSON ``id`` is not an outbox cursor and must not be sent as SSE ``id:``."""
    ephemeral_id = f"instance:{instance_id}:d:{turn_id}:{delta_seq}"
    return {
        "id": ephemeral_id,
        "type": "agent.message.delta",
        "at": datetime.now(timezone.utc).isoformat(),
        "instance_id": instance_id,
        "data": {
            "instance_id": instance_id,
            "turn_id": turn_id,
            "seq": delta_seq,
            "text": text,
        },
    }


async def stream_head(conn: AsyncConnection, stream: str) -> int:
    cur = await conn.execute("select last_seq from evidence.stream_heads where stream = %s", (stream,))
    row = await cur.fetchone()
    return int(row[0]) if row else 0


async def outbox_row_exists(conn: AsyncConnection, stream: str, seq: int) -> bool:
    cur = await conn.execute(
        "select 1 from evidence.outbox where stream = %s and seq = %s limit 1",
        (stream, seq),
    )
    return await cur.fetchone() is not None


async def validate_user_cursor(
    conn: AsyncConnection,
    *,
    person_id: str,
    cursor: str | None,
) -> CursorValidation:
    stream = ids.stream_user(person_id)
    if not cursor or not cursor.strip():
        return CursorValidation(ok=False, stream=stream, reason="cursor_unknown")

    try:
        parsed_stream, seq = ids.parse_ui_event_cursor(cursor.strip())
    except ValueError:
        return CursorValidation(ok=False, stream=stream, reason="cursor_unknown")

    if parsed_stream != stream:
        return CursorValidation(ok=False, stream=stream, seq=seq, reason="cursor_unknown")

    head = await stream_head(conn, stream)
    if seq > head:
        return CursorValidation(ok=False, stream=stream, seq=seq, reason="cursor_unknown")

    if seq > 0 and not await outbox_row_exists(conn, stream, seq):
        return CursorValidation(ok=False, stream=stream, seq=seq, reason="gap")

    return CursorValidation(ok=True, stream=stream, seq=seq)


async def validate_instance_cursor(
    conn: AsyncConnection,
    *,
    instance_id: str,
    cursor: str | None,
) -> CursorValidation:
    stream = ids.stream_instance(instance_id)
    if not cursor or not cursor.strip():
        return CursorValidation(ok=False, stream=stream, reason="cursor_unknown")

    try:
        parsed_stream, seq = ids.parse_ui_event_cursor(cursor.strip())
    except ValueError:
        return CursorValidation(ok=False, stream=stream, reason="cursor_unknown")

    if parsed_stream != stream:
        return CursorValidation(ok=False, stream=stream, seq=seq, reason="cursor_unknown")

    head = await stream_head(conn, stream)
    if seq > head:
        return CursorValidation(ok=False, stream=stream, seq=seq, reason="cursor_unknown")

    if seq > 0 and not await outbox_row_exists(conn, stream, seq):
        return CursorValidation(ok=False, stream=stream, seq=seq, reason="gap")

    return CursorValidation(ok=True, stream=stream, seq=seq)


async def fetch_outbox_after(
    conn: AsyncConnection, stream: str, after_seq: int
) -> list[tuple[str, int, str, str | None, dict[str, Any], dict[str, Any], datetime]]:
    cur = await conn.execute(
        "select stream, seq, event_type, instance_id, audience, data, created_at"
        " from evidence.outbox where stream = %s and seq > %s order by seq",
        (stream, after_seq),
    )
    rows = await cur.fetchall()
    out: list[tuple[str, int, str, str | None, dict[str, Any], dict[str, Any], datetime]] = []
    for row in rows:
        audience = row[4] if isinstance(row[4], dict) else json.loads(row[4])
        data = row[5] if isinstance(row[5], dict) else json.loads(row[5])
        out.append((row[0], int(row[1]), row[2], row[3], audience, data, row[6]))
    return out


async def participant_roles(conn: AsyncConnection, instance_id: str, person_id: str) -> list[str]:
    cur = await conn.execute(
        "select role from work.participants where instance_id = %s and person_id = %s",
        (instance_id, person_id),
    )
    return [r[0] for r in await cur.fetchall()]
