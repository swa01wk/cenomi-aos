"""Workflow timers: due selection and firing (M2-BE-05)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

from . import clock, ids, workflow
from .org import OrgModel
from .outbox import OutboxRow, append_outbox_many
from .workflow import _participants

log = logging.getLogger("aos.timers")

TimerOutcome = Literal["fired", "cancelled", "skipped", "missing"]


@dataclass(frozen=True)
class TimerProcessResult:
    timer_id: str
    outcome: TimerOutcome


async def due_timer_ids(conn: AsyncConnection, as_of: datetime) -> list[str]:
    cur = await conn.execute(
        "select id from work.timers"
        " where status = 'scheduled' and fires_at <= %s"
        " order by fires_at, id",
        (as_of,),
    )
    return [str(r[0]) for r in await cur.fetchall()]


async def process_due_timer(
    conn: AsyncConnection,
    timer_id: str,
    *,
    as_of: datetime,
    org: OrgModel,
    packs_dir: Path,
) -> TimerProcessResult:
    """Lock instance first, then the timer row. One timer per transaction."""
    cur = await conn.execute(
        "select instance_id from work.timers where id = %s",
        (timer_id,),
    )
    row = await cur.fetchone()
    if row is None:
        return TimerProcessResult(timer_id, "missing")
    instance_id = str(row[0])

    await conn.execute(
        "select id from work.instances where id = %s for update",
        (instance_id,),
    )
    cur = await conn.execute(
        "select id, name, emits, status from work.timers"
        " where id = %s for update skip locked",
        (timer_id,),
    )
    trow = await cur.fetchone()
    if trow is None:
        return TimerProcessResult(timer_id, "skipped")
    _tid, name, emits, status = trow
    if status != "scheduled":
        return TimerProcessResult(timer_id, "skipped")

    cur = await conn.execute(
        "select status from work.instances where id = %s",
        (instance_id,),
    )
    inst_row = await cur.fetchone()
    inst_status = inst_row[0] if inst_row else None
    if inst_status != "running":
        await conn.execute(
            "update work.timers set status = 'cancelled' where id = %s",
            (timer_id,),
        )
        return TimerProcessResult(timer_id, "cancelled")

    await conn.execute(
        "update work.timers set status = 'fired', fired_at = %s where id = %s",
        (as_of, timer_id),
    )
    participants = await _participants(conn, instance_id)
    roles = [r for r, _ in participants]
    data = {"instance_id": instance_id, "timer": name, "emits": emits}
    await append_outbox_many(
        conn,
        [
            OutboxRow(
                stream=ids.stream_instance(instance_id),
                event_type="timer.fired",
                instance_id=instance_id,
                audience={"roles": roles},
                data=data,
            ),
        ],
    )
    await workflow.apply_event(
        conn,
        instance_id,
        f"timer.{emits}",
        by_role=None,
        packs_dir=packs_dir,
        org=org,
        actor={"kind": "kernel", "id": "scheduler"},
    )
    return TimerProcessResult(timer_id, "fired")


async def run_timer_tick(
    pool: AsyncConnectionPool,
    *,
    as_of: datetime,
    org: OrgModel,
    packs_dir: Path,
) -> list[TimerProcessResult]:
    async with pool.connection() as conn:
        candidates = await due_timer_ids(conn, as_of)
    results: list[TimerProcessResult] = []
    for timer_id in candidates:
        try:
            async with pool.connection() as conn:
                async with conn.transaction():
                    result = await process_due_timer(
                        conn,
                        timer_id,
                        as_of=as_of,
                        org=org,
                        packs_dir=packs_dir,
                    )
            results.append(result)
        except Exception:  # noqa: BLE001 — other timers still run
            log.exception("timer %s failed", timer_id)
    return results
