"""Conversation turns (M1)."""

from __future__ import annotations

from typing import Any

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from . import ids


def text_blocks(text: str) -> list[dict[str, Any]]:
    return [{"kind": "text", "text": text}]


async def next_turn_seq(conn: AsyncConnection, instance_id: str) -> int:
    cur = await conn.execute(
        "select coalesce(max(seq), 0) + 1 from work.turns where instance_id = %s",
        (instance_id,),
    )
    row = await cur.fetchone()
    return int(row[0])


async def find_turn_by_client_id(
    conn: AsyncConnection, instance_id: str, author_id: str, client_turn_id: str
) -> tuple | None:
    cur = await conn.execute(
        "select id, seq, author_kind, author_id, audience_roles, blocks, attempt_id, at from work.turns"
        " where instance_id = %s and author_id = %s and client_turn_id = %s",
        (instance_id, author_id, client_turn_id),
    )
    return await cur.fetchone()


async def insert_agent_turn(
    conn: AsyncConnection,
    *,
    instance_id: str,
    seat_id: str,
    seat_name: str,
    blocks: list[dict[str, Any]],
    audience_roles: list[str] | None,
    attempt_id: str | None,
) -> dict[str, Any]:
    turn_id = ids.new_turn_id()
    seq = await next_turn_seq(conn, instance_id)
    await conn.execute(
        "insert into work.turns ("
        " id, instance_id, seq, author_kind, author_id, audience_roles, blocks, attempt_id"
        ") values (%s, %s, %s, 'seat', %s, %s, %s, %s)",
        (turn_id, instance_id, seq, seat_id, audience_roles, Jsonb(blocks), attempt_id),
    )
    cur = await conn.execute("select at from work.turns where id = %s", (turn_id,))
    at_row = await cur.fetchone()
    return {
        "turn_id": turn_id,
        "seq": seq,
        "blocks": blocks,
        "at": at_row[0].isoformat() if at_row else "",
        "attempt_id": attempt_id,
        "author": {"kind": "seat", "id": seat_id, "name": seat_name},
    }


async def insert_person_turn(
    conn: AsyncConnection,
    *,
    instance_id: str,
    person_id: str,
    text: str,
    client_turn_id: str,
    audience_roles: list[str] | None = None,
    attempt_id: str | None = None,
) -> dict[str, Any]:
    turn_id = ids.new_turn_id()
    seq = await next_turn_seq(conn, instance_id)
    blocks = text_blocks(text)
    await conn.execute(
        "insert into work.turns ("
        " id, instance_id, seq, author_kind, author_id, audience_roles, blocks, attempt_id, client_turn_id"
        ") values (%s, %s, %s, 'person', %s, %s, %s, %s, %s)",
        (
            turn_id,
            instance_id,
            seq,
            person_id,
            audience_roles,
            Jsonb(blocks),
            attempt_id,
            client_turn_id,
        ),
    )
    cur = await conn.execute("select at from work.turns where id = %s", (turn_id,))
    at_row = await cur.fetchone()
    return {
        "turn_id": turn_id,
        "seq": seq,
        "blocks": blocks,
        "at": at_row[0].isoformat() if at_row else "",
        "attempt_id": attempt_id,
    }


def project_turn(row: tuple, *, person_name: str) -> dict[str, Any]:
    """``person_name`` is the author's display name: the person's name, or the Seat's display name."""
    turn_id, seq, author_kind, author_id, _audience, blocks, attempt_id, at = row
    author_name = person_name or author_id
    return {
        "turn_id": turn_id,
        "seq": seq,
        "author": {"kind": author_kind, "id": author_id, "name": author_name},
        "blocks": blocks if isinstance(blocks, list) else [],
        "at": at.isoformat() if hasattr(at, "isoformat") else str(at),
        "attempt_id": attempt_id,
    }


def turn_visible(audience_roles: list[str] | None, viewer_roles: list[str]) -> bool:
    if not audience_roles:
        return True
    return bool(set(audience_roles) & set(viewer_roles))
