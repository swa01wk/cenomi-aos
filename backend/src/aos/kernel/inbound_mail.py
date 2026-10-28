"""Inbound connector notifications: dedupe, instance ref, trigger context for event Tasks."""

from __future__ import annotations

from typing import Any

from psycopg import AsyncConnection
from psycopg.errors import UniqueViolation
from psycopg.types.json import Jsonb


def parse_instance_ref(ref: str) -> tuple[str | None, str | None]:
    """``QQ-0019:SUP-11632`` → instance id and counterparty key from the thread ref."""
    if ":" not in ref:
        return None, None
    instance_id, party_id = ref.split(":", 1)
    instance_id = instance_id.strip() or None
    party_id = party_id.strip() or None
    return instance_id, party_id


def trigger_context_from_payload(*, event: str, payload: dict[str, Any]) -> dict[str, Any]:
    ref = str(payload.get("ref") or "")
    _inst, party_id = parse_instance_ref(ref)
    return {
        "event": event,
        "conversation_id": str(payload.get("conversation_id") or ""),
        "message_id": str(payload.get("message_id") or ""),
        "party_id": party_id or "",
        "sender": str(payload.get("sender") or payload.get("from") or ""),
        "ref": ref,
    }


async def record_inbound_message(
    conn: AsyncConnection,
    *,
    source: str,
    payload: dict[str, Any],
) -> tuple[bool, str | None]:
    """Insert inbound row; return (is_new, instance_id from ref). Duplicates are ignored."""
    message_id = str(payload.get("message_id") or "")
    conversation_id = str(payload.get("conversation_id") or "")
    if not message_id or not conversation_id:
        raise ValueError("inbound payload missing message_id or conversation_id")
    ref = str(payload.get("ref") or "")
    instance_id, _ = parse_instance_ref(ref)
    received_at = payload.get("received_at")
    try:
        await conn.execute(
            """
            insert into work.inbound_messages (
              source, message_id, conversation_id, instance_id, payload, received_at
            ) values (%s, %s, %s, %s, %s, coalesce(%s::timestamptz, now()))
            """,
            (source, message_id, conversation_id, instance_id, Jsonb(payload), received_at),
        )
        return True, instance_id
    except UniqueViolation:
        return False, instance_id
