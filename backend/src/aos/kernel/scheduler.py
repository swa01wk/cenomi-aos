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

from pathlib import Path

from . import clock, readiness, timers
from .org import OrgModel
from .worker_attempts import expire_one_attempt, readmit_after_expiry_lease

log = logging.getLogger("aos.scheduler")

ADVISORY_LOCK_KEY = 8070501


async def run_lease_expiry_tick(
    pool: AsyncConnectionPool,
    *,
    database_url: str,
    org: OrgModel | None = None,
) -> int:
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
                    outcome = await expire_one_attempt(conn, org=org)
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


async def run_timer_tick(
    pool: AsyncConnectionPool,
    *,
    org: OrgModel,
    packs_dir: Path,
) -> int:
    as_of = clock.now()
    results = await timers.run_timer_tick(pool, as_of=as_of, org=org, packs_dir=packs_dir)
    fired = sum(1 for r in results if r.outcome == "fired")
    return fired


async def scheduler_loop(
    pool: AsyncConnectionPool,
    *,
    database_url: str,
    interval_s: float,
    stop: asyncio.Event,
    org: OrgModel,
    packs_dir: Path,
) -> None:
    while not stop.is_set():
        try:
            n = await run_lease_expiry_tick(pool, database_url=database_url, org=org)
            if n:
                log.debug("expired %s worker lease(s)", n)
            t = await run_timer_tick(pool, org=org, packs_dir=packs_dir)
            if t:
                log.debug("fired %s timer(s)", t)
            r = await readiness.run_readiness_tick(pool, org=org, packs_dir=packs_dir)
            if any(x.outcome == "admitted" for x in r):
                log.debug("readiness admitted %s task(s)", sum(1 for x in r if x.outcome == "admitted"))
        except Exception:  # noqa: BLE001 - loop keeps running
            log.exception("scheduler tick failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_s)
        except TimeoutError:
            continue


def start_scheduler(
    pool: AsyncConnectionPool,
    *,
    database_url: str,
    interval_s: float,
    org: OrgModel,
    packs_dir: Path,
) -> tuple[asyncio.Task, asyncio.Event]:
    stop = asyncio.Event()
    task = asyncio.create_task(
        scheduler_loop(
            pool,
            database_url=database_url,
            interval_s=interval_s,
            stop=stop,
            org=org,
            packs_dir=packs_dir,
        ),
        name="aos-scheduler",
    )
    return task, stop
