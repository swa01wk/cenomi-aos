"""askQuestions: agent turn and WAITING_INPUT (M1-BE-05-B)."""

from __future__ import annotations

from typing import Any

from psycopg import AsyncConnection

from .conversation import insert_agent_turn
from .outbox import OutboxRow, append_outbox_many
from . import ids
from .worker_attempts import (
    _instance_participant_audience,
    emit_task_state_changed,
    end_claimed_attempt,
    seat_display_name,
)
from .worker_fence import CommittedFenced, require_claimed_attempt


def _blocks_with_questions(blocks: list[dict[str, Any]], questions: list[str] | None) -> list[dict[str, Any]]:
    out = list(blocks)
    for q in questions or []:
        out.append({"kind": "text", "text": q})
    return out


async def ask_questions(
    conn: AsyncConnection,
    *,
    org_id: str,
    attempt_id: str,
    worker_id: str,
    fencing_token: int,
    blocks: list[dict[str, Any]],
    questions: list[str] | None,
) -> dict[str, Any] | CommittedFenced:
    gate = await require_claimed_attempt(
        conn, org_id=org_id, attempt_id=attempt_id, worker_id=worker_id, fencing_token=fencing_token
    )
    if isinstance(gate, CommittedFenced):
        return gate

    audience = await _instance_participant_audience(conn, gate.instance_id)
    audience_roles = audience.get("roles")
    author_name = await seat_display_name(
        conn, org_id=gate.org_id, seat_name=gate.seat, seat_version=gate.seat_version
    )
    merged_blocks = _blocks_with_questions(blocks, questions)
    turn = await insert_agent_turn(
        conn,
        instance_id=gate.instance_id,
        seat_id=gate.seat,
        seat_name=author_name,
        blocks=merged_blocks,
        audience_roles=audience_roles,
        attempt_id=attempt_id,
    )
    turn_payload = {
        "turn_id": turn["turn_id"],
        "seq": turn["seq"],
        "author": turn["author"],
        "blocks": turn["blocks"],
        "at": turn["at"],
        "attempt_id": attempt_id,
    }
    from_state = gate.task_state
    end = await end_claimed_attempt(
        conn,
        org_id=org_id,
        attempt_id=attempt_id,
        worker_id=worker_id,
        fencing_token=fencing_token,
        outcome="needs_input",
        reserve_if_empty=False,
    )
    if not end.ended:
        if end.fenced is not None:
            return end.fenced
        raise RuntimeError("askQuestions could not end the attempt")

    await conn.execute(
        "update work.tasks set state = 'WAITING_INPUT', updated_at = now() where id = %s",
        (gate.task_id,),
    )
    if from_state != "WAITING_INPUT":
        await emit_task_state_changed(
            conn,
            instance_id=gate.instance_id,
            task_id=gate.task_id,
            template=gate.contract.get("template", "assist"),
            from_state=from_state,
            to_state="WAITING_INPUT",
        )
    await append_outbox_many(
        conn,
        [
            OutboxRow(
                stream=ids.stream_instance(gate.instance_id),
                event_type="agent.message.completed",
                instance_id=gate.instance_id,
                audience=audience,
                data={"instance_id": gate.instance_id, "turn": turn_payload},
            )
        ],
    )
    return turn_payload
