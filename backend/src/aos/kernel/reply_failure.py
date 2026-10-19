"""Tell the participant when an assist reply can't be finished, instead of leaving the chat silent."""

from __future__ import annotations

from typing import Any

from psycopg import AsyncConnection

from . import ids
from .conversation import insert_agent_turn
from .outbox import OutboxRow, append_outbox_many

_REASONS = {
    "budget_exhausted": "I reached my limit for a single reply",
    "tool_timeout": "a system I rely on didn't answer in time",
    "invalid_output": "my answer didn't pass its checks",
    "expired": "I stopped responding",
}


def reply_failed_text(failure_class: str) -> str:
    reason = _REASONS.get(failure_class)
    head = f"I couldn't finish this reply: {reason}." if reason else "I couldn't finish this reply."
    return f"{head} Send your message again; if it keeps happening, tell the owner of this digital worker."


async def post_reply_failed(
    conn: AsyncConnection,
    *,
    org_id: str,
    instance_id: str,
    seat: str,
    seat_version: int,
    attempt_id: str,
    failure_class: str,
) -> dict[str, Any]:
    """Add a seat turn with a notice block and emit agent.message.completed, in the caller's transaction.

    Only for assist attempts that end for good (no retry follows). The notice names the kind of failure, never its
    details: those stay in the execution events.
    """
    from .worker_attempts import _instance_participant_audience, seat_display_name

    audience = await _instance_participant_audience(conn, instance_id)
    author_name = await seat_display_name(conn, org_id=org_id, seat_name=seat, seat_version=seat_version)
    blocks = [{"kind": "notice", "tone": "bad", "text": reply_failed_text(failure_class)}]
    turn = await insert_agent_turn(
        conn,
        instance_id=instance_id,
        seat_id=seat,
        seat_name=author_name,
        blocks=blocks,
        audience_roles=audience.get("roles"),
        attempt_id=attempt_id,
    )
    payload = {
        "turn_id": turn["turn_id"],
        "seq": turn["seq"],
        "author": turn["author"],
        "blocks": turn["blocks"],
        "at": turn["at"],
        "attempt_id": attempt_id,
    }
    await append_outbox_many(
        conn,
        [
            OutboxRow(
                stream=ids.stream_instance(instance_id),
                event_type="agent.message.completed",
                instance_id=instance_id,
                audience=audience,
                data={"instance_id": instance_id, "turn": payload},
            )
        ],
    )
    return payload
