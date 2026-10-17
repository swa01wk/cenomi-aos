"""Background scheduler: lease expiry (M1-BE-05-A). M2 adds timers and reconciliation.

The lease-expiry advisory lock is taken on a dedicated connection (not from the pool), so a failed
``pg_advisory_unlock`` or a poisoned session never returns a broken connection to the pool. The
connection is always closed in ``finally``.
"""

from __future__ import annotations

import asyncio
import logging

import psycopg
from psycopg_pool import AsyncConnectionPool

from .worker_attempts import expire_one_attempt, readmit_after_expiry_lease

log = logging.getLogger("aos.scheduler")

ADVISORY_LOCK_KEY = 8070501


async def run_lease_expiry_tick(pool: AsyncConnectionPool, *, database_url: str) -> int:
    """Expire due leases; expiry and re-admission each commit in their own transaction."""
    lock_conn = await psycopg.AsyncConnection.connect(database_url)
    acquired = False
    try:
        cur = await lock_conn.execute("select pg_try_advisory_lock(%s)", (ADVISORY_LOCK_KEY,))
        row = await cur.fetchone()
        acquired = bool(row and row[0])
        if not acquired:
            return 0
        expired_count = 0
        while True:
            async with pool.connection() as conn:
                async with conn.transaction():
                    outcome = await expire_one_attempt(conn)
            if not outcome.expired:
                break
            expired_count += 1
            if outcome.readmit is not None:
                async with pool.connection() as conn:
                    async with conn.transaction():
                        await readmit_after_expiry_lease(conn, outcome.readmit)
        return expired_count
    finally:
        if acquired:
            try:
                await lock_conn.execute("select pg_advisory_unlock(%s)", (ADVISORY_LOCK_KEY,))
            except Exception:  # noqa: BLE001 - still close the session
                log.exception("advisory unlock failed")
        await lock_conn.close()


async def scheduler_loop(
    pool: AsyncConnectionPool, *, database_url: str, interval_s: float, stop: asyncio.Event
) -> None:
    while not stop.is_set():
        try:
            n = await run_lease_expiry_tick(pool, database_url=database_url)
            if n:
                log.debug("expired %s worker lease(s)", n)
        except Exception:  # noqa: BLE001 - loop keeps running
            log.exception("scheduler tick failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_s)
        except TimeoutError:
            continue


def start_scheduler(
    pool: AsyncConnectionPool, *, database_url: str, interval_s: float
) -> tuple[asyncio.Task, asyncio.Event]:
    stop = asyncio.Event()
    task = asyncio.create_task(
        scheduler_loop(pool, database_url=database_url, interval_s=interval_s, stop=stop),
        name="aos-scheduler",
    )
    return task, stop
