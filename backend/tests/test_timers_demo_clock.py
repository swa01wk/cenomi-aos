"""M2-BE-05 part 1: kernel clock, timer tick and demo operations."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from aos.api import create_app
from aos.kernel import clock, demo, ids, timers, workflow
from aos.kernel.org import load_org, seed_sql
from aos.kernel.registry_store import sync_pack
from aos.kernel.settings import REPO, Settings

from . import _pg

ORG = load_org(REPO / "seed" / "org.yaml")
ORG_ID = ORG.organization.id
PACKS = REPO / "packs"
SEAT = "seat_sourcing_poc"
WORKFLOW = "quick_quote"


async def _sync_published(conn, packs_dir: Path) -> str:
    result = await sync_pack(
        conn,
        org=ORG,
        packs_dir=packs_dir,
        name="procurement_demo",
        actor="platform_admin",
        source="test",
    )
    await conn.execute(
        "update registry.pack_versions set status = 'published' where id = %s",
        (result.pack_version_id,),
    )
    return result.pack_version_id


async def _insert_instance(
    conn,
    *,
    instance_id: str,
    pack_version_id: str,
    state: str = "intake",
    version: int = 1,
    attributes: dict | None = None,
    status: str = "running",
) -> None:
    attrs = attributes or {}
    await conn.execute(
        """
        insert into work.instances (
          id, org_id, workflow, pack_version_id, seat, seat_version, title, state, version,
          attributes, created_by, correlation_id, status
        ) values (%s, %s, %s, %s, %s, 1, 'Test job', %s, %s, %s, 'faisal', %s, %s)
        """,
        (
            instance_id,
            ORG_ID,
            WORKFLOW,
            pack_version_id,
            SEAT,
            state,
            version,
            json.dumps(attrs),
            f"corr_{instance_id}",
            status,
        ),
    )
    await conn.execute(
        "insert into work.participants (instance_id, role, person_id, bound_by)"
        " values (%s, 'requester', 'faisal', 'creation'), (%s, 'buyer', 'noura', 'claim')",
        (instance_id, instance_id),
    )


async def _insert_due_timer(
    conn,
    *,
    instance_id: str,
    name: str = "quote_deadline",
    emits: str = "quotes_closed",
    fires_at: datetime | None = None,
) -> str:
    at = fires_at or clock.now() - timedelta(minutes=1)
    tid = ids.new_timer_id()
    await conn.execute(
        "insert into work.timers (id, instance_id, name, emits, fires_at, status, generation)"
        " values (%s, %s, %s, %s, %s, 'scheduled', 1)",
        (tid, instance_id, name, emits, at),
    )
    return tid


@unittest.skipUnless(_pg.available(), "no local Postgres")
class TimerTickTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.db = _pg.create_migrated()
        self.url = _pg.kernel_url(self.db)
        self.tmp = Path(tempfile.mkdtemp())
        shutil.copytree(PACKS / "procurement_demo", self.tmp / "procurement_demo")
        async with await psycopg.AsyncConnection.connect(self.url) as conn:
            await conn.execute(seed_sql(ORG))
            self.pvid = await _sync_published(conn, self.tmp)
        clock.configure(demo_enabled=True, offset_seconds=0)

    async def asyncTearDown(self) -> None:
        clock.configure(demo_enabled=False, offset_seconds=0)
        clock.set_frozen_wall(None)
        _pg.drop(self.db)
        shutil.rmtree(self.tmp, ignore_errors=True)

    async def test_due_timer_on_cancelled_job_is_cancelled_and_tick_ends(self) -> None:
        inst = "QQ-T01"
        async with await psycopg.AsyncConnection.connect(self.url) as conn:
            async with conn.transaction():
                await _insert_instance(
                    conn,
                    instance_id=inst,
                    pack_version_id=self.pvid,
                    state="awaiting_quotes",
                    status="cancelled",
                )
                tid = await _insert_due_timer(conn, instance_id=inst)
            as_of = clock.now()
            async with self._open_pool() as pool:
                results = await timers.run_timer_tick(
                    pool, as_of=as_of, org=ORG, packs_dir=self.tmp
                )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].outcome, "cancelled")
        async with await psycopg.AsyncConnection.connect(self.url, row_factory=dict_row) as conn:
            row = await (
                await conn.execute("select status from work.timers where id = %s", (tid,))
            ).fetchone()
            self.assertEqual(row["status"], "cancelled")
            again = await timers.due_timer_ids(conn, as_of)
            self.assertEqual(again, [])

    async def test_two_ticks_race_fire_once(self) -> None:
        inst = "QQ-T02"
        wall = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
        clock.set_frozen_wall(wall)
        async with await psycopg.AsyncConnection.connect(self.url) as conn:
            async with conn.transaction():
                await _insert_instance(
                    conn,
                    instance_id=inst,
                    pack_version_id=self.pvid,
                    state="awaiting_quotes",
                    attributes={"quote_count": 2},
                )
                tid = await _insert_due_timer(conn, instance_id=inst)
            as_of = clock.now()

            async def race_once() -> timers.TimerProcessResult:
                async with await psycopg.AsyncConnection.connect(self.url) as c1:
                    async with c1.transaction():
                        return await timers.process_due_timer(
                            c1, tid, as_of=as_of, org=ORG, packs_dir=self.tmp
                        )

            a, b = await asyncio.gather(race_once(), race_once())
            outcomes = {a.outcome, b.outcome}
            self.assertEqual(outcomes, {"fired", "skipped"})
        async with await psycopg.AsyncConnection.connect(self.url, row_factory=dict_row) as conn:
            t = await (
                await conn.execute("select status from work.timers where id = %s", (tid,))
            ).fetchone()
            self.assertEqual(t["status"], "fired")
            i = await (
                await conn.execute("select state from work.instances where id = %s", (inst,))
            ).fetchone()
            self.assertEqual(i["state"], "comparison")
            fired = await (
                await conn.execute(
                    "select count(*) as c from evidence.outbox"
                    " where instance_id = %s and event_type = 'timer.fired'",
                    (inst,),
                )
            ).fetchone()
            self.assertEqual(int(fired["c"]), 1)

    async def test_cancel_timers_racing_fire_no_deadlock(self) -> None:
        inst = "QQ-T03"
        wall = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
        clock.set_frozen_wall(wall)
        async with await psycopg.AsyncConnection.connect(self.url) as conn:
            async with conn.transaction():
                await _insert_instance(
                    conn,
                    instance_id=inst,
                    pack_version_id=self.pvid,
                    state="ordering",
                    version=6,
                    attributes={"quote_count": 2, "shortlist_count": 3},
                )
                tid = await _insert_due_timer(conn, instance_id=inst)
            as_of = clock.now()

            async def fire() -> timers.TimerProcessResult:
                async with await psycopg.AsyncConnection.connect(self.url) as c1:
                    async with c1.transaction():
                        return await timers.process_due_timer(
                            c1, tid, as_of=as_of, org=ORG, packs_dir=self.tmp
                        )

            async def close_with_cancel() -> workflow.ApplyEventResult:
                async with await psycopg.AsyncConnection.connect(self.url) as c2:
                    async with c2.transaction():
                        return await workflow.apply_event(
                            c2,
                            inst,
                            "task.completed.po_create",
                            by_role=None,
                            packs_dir=self.tmp,
                            org=ORG,
                        )

            await asyncio.gather(fire(), close_with_cancel())
            status = await self._timer_status(tid)
            self.assertIn(status, ("fired", "cancelled"))
            self.assertNotEqual(status, "scheduled")

    async def test_demo_after_only_when_demo_enabled(self) -> None:
        wall = datetime(2026, 6, 3, 12, 0, tzinfo=UTC)
        clock.set_frozen_wall(wall)
        async with await psycopg.AsyncConnection.connect(self.url) as conn:
            for inst, demo_on in (("QQ-T04A", False), ("QQ-T04B", True)):
                async with conn.transaction():
                    await _insert_instance(
                        conn,
                        instance_id=inst,
                        pack_version_id=self.pvid,
                        state="rfq_sending",
                        version=4,
                        attributes={"shortlist_count": 3},
                    )
                clock.configure(demo_enabled=demo_on, offset_seconds=0)
                async with conn.transaction():
                    await workflow.apply_event(
                        conn,
                        inst,
                        "task.completed.rfq_send",
                        by_role=None,
                        packs_dir=self.tmp,
                        org=ORG,
                    )
                row = await (
                    await conn.execute(
                        "select fires_at from work.timers where instance_id = %s",
                        (inst,),
                    )
                ).fetchone()
                duration = "1m" if demo_on else "5d"
                expected = wall + clock.parse_duration(duration)
                self.assertEqual(row[0].replace(microsecond=0), expected.replace(microsecond=0))

    async def test_advance_clock_fires_timer_and_moves_job(self) -> None:
        inst = "QQ-T05"
        wall = datetime(2026, 6, 4, 12, 0, tzinfo=UTC)
        clock.set_frozen_wall(wall)
        fires = wall + timedelta(minutes=30)
        async with await psycopg.AsyncConnection.connect(self.url) as conn:
            async with conn.transaction():
                await _insert_instance(
                    conn,
                    instance_id=inst,
                    pack_version_id=self.pvid,
                    state="awaiting_quotes",
                    version=5,
                    attributes={"quote_count": 2, "shortlist_count": 3},
                )
                await _insert_due_timer(conn, instance_id=inst, fires_at=fires)
                await demo.ensure_demo_clock_row(conn, ORG_ID)
            async with conn.transaction():
                await demo.advance_demo_clock(conn, ORG_ID, minutes=45)
            clock.set_offset(45 * 60)
            async with self._open_pool() as pool:
                await timers.run_timer_tick(
                    pool, as_of=clock.now(), org=ORG, packs_dir=self.tmp
                )
        async with await psycopg.AsyncConnection.connect(self.url, row_factory=dict_row) as conn:
            row = await (
                await conn.execute("select state from work.instances where id = %s", (inst,))
            ).fetchone()
            self.assertEqual(row["state"], "comparison")

    async def test_advance_demo_clock_does_not_expire_worker_lease(self) -> None:
        inst = "QQ-T06"
        async with await psycopg.AsyncConnection.connect(self.url) as conn:
            async with conn.transaction():
                await _insert_instance(conn, instance_id=inst, pack_version_id=self.pvid)
                task_id = ids.new_task_id()
                await conn.execute(
                    """
                    insert into work.tasks (
                      id, instance_id, template, skill, work_type, state, kind,
                      fencing_token, attempts_used, max_attempts, contract, contract_hash
                    ) values (%s, %s, 'request_intake', 'request_intake', 'conversation', 'RUNNING', 'assist',
                      1, 1, 3, '{}', 'hash')
                    """,
                    (task_id, inst),
                )
                att = ids.new_attempt_id()
                lease_until = datetime.now(UTC) + timedelta(seconds=90)
                await conn.execute(
                    """
                    insert into work.attempts (
                      id, task_id, n, state, worker_id, fencing_token, lease_expires_at, reserved_usd
                    ) values (%s, %s, 1, 'CLAIMED', 'w1', 1, %s, 0)
                    """,
                    (att, task_id, lease_until),
                )
                await demo.ensure_demo_clock_row(conn, ORG_ID)
            async with conn.transaction():
                await demo.advance_demo_clock(conn, ORG_ID, minutes=60 * 24 * 30)
            clock.set_offset(60 * 24 * 30 * 60)
            from aos.kernel.scheduler import run_lease_expiry_tick

            async with self._open_pool() as pool:
                n = await run_lease_expiry_tick(pool, database_url=self.url)
            self.assertEqual(n, 0)
        async with await psycopg.AsyncConnection.connect(self.url, row_factory=dict_row) as conn:
            st = await (
                await conn.execute("select state from work.attempts where id = %s", (att,))
            ).fetchone()
            self.assertEqual(st["state"], "CLAIMED")

    def _open_pool(self):
        from contextlib import asynccontextmanager

        from psycopg_pool import AsyncConnectionPool

        @asynccontextmanager
        async def _pool():
            pool = AsyncConnectionPool(self.url, min_size=1, max_size=4)
            await pool.open()
            try:
                yield pool
            finally:
                await pool.close()

        return _pool()

    async def _timer_status(self, tid: str) -> str:
        async with await psycopg.AsyncConnection.connect(self.url, row_factory=dict_row) as conn:
            t = await (
                await conn.execute("select status from work.timers where id = %s", (tid,))
            ).fetchone()
            return str(t["status"])


class DemoApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not _pg.available():
            return
        cls.db = _pg.create_migrated()
        cls.url = _pg.kernel_url(cls.db)
        cls.settings = Settings.from_env(
            database_url=cls.url,
            seed_on_start=False,
            demo=True,
            session_secret="test-secret-" + "x" * 40,
        )
        asyncio.run(cls._seed())
        cls.client = TestClient(create_app(cls.settings))
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        if hasattr(cls, "client"):
            cls.client.__exit__(None, None, None)
        if hasattr(cls, "db"):
            _pg.drop(cls.db)

    def setUp(self) -> None:
        if not _pg.available():
            self.skipTest("no postgres")
        clock.configure(demo_enabled=True, offset_seconds=0)

    def tearDown(self) -> None:
        clock.configure(demo_enabled=False, offset_seconds=0)

    @classmethod
    async def _seed(cls) -> None:
        async with await psycopg.AsyncConnection.connect(cls.url) as conn:
            await conn.execute(seed_sql(ORG))

    def _login(self, person: str = "platform_admin") -> dict[str, str]:
        return self._login_on(self.client, person)

    def _login_on(self, client: TestClient, person: str = "platform_admin") -> dict[str, str]:
        r = client.post("/api/auth/session", json={"person_id": person})
        self.assertEqual(r.status_code, 200, r.text)
        return {"Authorization": f"Bearer {r.json()['token']}"}

    def test_demo_endpoints_404_without_aos_demo(self) -> None:
        off = Settings.from_env(
            database_url=self.url,
            seed_on_start=False,
            demo=False,
            session_secret="test-secret-" + "x" * 40,
        )
        with TestClient(create_app(off)) as client:
            h = self._login_on(client)
            self.assertEqual(client.get("/api/demo/state", headers=h).status_code, 404)
            self.assertEqual(
                client.post("/api/demo/clock/advance", headers=h, json={"minutes": 5}).status_code,
                404,
            )

    def test_get_demo_state_and_advance_contract_shape(self) -> None:
        h = self._login()
        r = self.client.get("/api/demo/state", headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertIn("now", body)
        self.assertIn("timers", body)
        self.assertEqual(body["faults"], {})
        adv = self.client.post("/api/demo/clock/advance", headers=h, json={"minutes": 1})
        self.assertEqual(adv.status_code, 200, adv.text)
        self.assertIn("now", adv.json())


if __name__ == "__main__":
    unittest.main()
