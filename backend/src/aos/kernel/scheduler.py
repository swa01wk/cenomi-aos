"""Background scheduler: lease expiry (M1-BE-05-A). M2 adds timers and reconciliation."""

from __future__ import annotations

import asyncio
import logging

from psycopg_pool import AsyncConnectionPool

from .worker_attempts import expire_one_attempt, readmit_after_expiry_lease

log = logging.getLogger("aos.scheduler")

ADVISORY_LOCK_KEY = 8070501


async def run_lease_expiry_tick(pool: AsyncConnectionPool) -> int:
    """Expire due leases; expiry and re-admission each commit in their own transaction."""
    async with pool.connection() as lock_conn:
        cur = await lock_conn.execute("select pg_try_advisory_lock(%s)", (ADVISORY_LOCK_KEY,))
        row = await cur.fetchone()
        if not row or not row[0]:
            return 0
        try:
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
            await lock_conn.execute("select pg_advisory_unlock(%s)", (ADVISORY_LOCK_KEY,))


async def scheduler_loop(pool: AsyncConnectionPool, *, interval_s: float, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            n = await run_lease_expiry_tick(pool)
            if n:
                log.debug("expired %s worker lease(s)", n)
        except Exception:  # noqa: BLE001 - loop keeps running
            log.exception("scheduler tick failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_s)
        except TimeoutError:
            continue


def start_scheduler(pool: AsyncConnectionPool, *, interval_s: float) -> tuple[asyncio.Task, asyncio.Event]:
    stop = asyncio.Event()
    task = asyncio.create_task(scheduler_loop(pool, interval_s=interval_s, stop=stop), name="aos-scheduler")
    return task, stop
