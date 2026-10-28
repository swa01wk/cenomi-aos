"""M1-BE-05-A: worker auth, fencing, claim, heartbeat, contract, fail, scheduler."""

from __future__ import annotations

import asyncio
import shutil
import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import psycopg
from fastapi.testclient import TestClient
from psycopg_pool import AsyncConnectionPool

from aos.api import create_app
from aos.kernel.auth import issue_worker_token
from aos.kernel.org import load_org
from aos.kernel.scheduler import ADVISORY_LOCK_KEY, run_lease_expiry_tick
from aos.kernel.seats import insert_seats_for_published_pack
from aos.kernel.settings import REPO, Settings
from aos.kernel.worker_attempts import expire_one_attempt, readmit_after_expiry_lease

from . import _pg
from ._packs import copy_demo_pack

ORG = load_org(REPO / "seed" / "org.yaml")
SEAT = "seat_sourcing_poc"
WORKFLOW = "quick_quote"


def _failure_notices(db, instance_id: str | None = None) -> list[str]:
    """Texts of seat turns carrying a 'notice' block (the reply-failed message)."""
    where = f" and instance_id = '{instance_id}'" if instance_id else ""
    out = _pg.admin_sql(
        db,
        "select b->>'text' from work.turns t, jsonb_array_elements(t.blocks) b"
        f" where t.author_kind = 'seat' and b->>'kind' = 'notice'{where} order by t.seq;",
    ).stdout.strip()
    return [line for line in out.splitlines() if line]


class WorkerHarness(unittest.TestCase):
    """Shared Postgres app fixture for worker protocol tests (no test methods)."""

    # Worker protocol suites drive assist turns; suites for the intake Task set this.
    INTAKE_TASK = False

    @classmethod
    def setUpClass(cls) -> None:
        cls.db = _pg.create_migrated()
        cls.packs = Path(tempfile.mkdtemp(prefix="aos-packs-worker-"))
        copy_demo_pack(cls.packs, intake_task=cls.INTAKE_TASK)
        cls.settings = Settings.from_env(
            database_url=_pg.kernel_url(cls.db),
            packs_dir=cls.packs,
            session_secret="test-secret-" + "x" * 40,
            scheduler_interval_seconds=60.0,
            connector_secrets={"mock_erp": "erp-test-secret", "mock_mail": "mail-test-secret"},
        )
        cls.client = TestClient(create_app(cls.settings))
        cls.client.__enter__()
        cls.version_id = cls.client.post(
            "/api/console/packs/procurement_demo/sync",
            headers=cls._auth("platform_admin"),
            json={"source": "test"},
        ).json()["pack_version_id"]
        cls._publish_once()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client.__exit__(None, None, None)
        _pg.drop(cls.db)
        shutil.rmtree(cls.packs, ignore_errors=True)

    @classmethod
    def _auth(cls, person: str) -> dict:
        token = cls.client.post("/api/auth/session", json={"person_id": person}).json()["token"]
        return {"Authorization": f"Bearer {token}"}

    def worker_auth(self, worker_id: str = "worker-test-1") -> dict:
        token = issue_worker_token(ORG.organization.id, worker_id, self.settings.session_secret)
        return {"Authorization": f"Bearer {token}"}

    @classmethod
    def _publish_once(cls) -> None:
        cls.client.post(
            f"/api/console/pack-versions/{cls.version_id}/publish-requests",
            headers=cls._auth("platform_admin"),
        )
        req = cls.client.get("/api/console/publish-requests", headers=cls._auth("risk")).json()["items"][0]
        cls.client.post(
            f"/api/console/publish-requests/{req['id']}/approve",
            headers=cls._auth("risk"),
            json={"part": "policies"},
        )
        cls.client.post(
            f"/api/console/publish-requests/{req['id']}/approve",
            headers=cls._auth("head_of_procurement"),
            json={"part": "seats_and_workflows"},
        )

    def setUp(self) -> None:
        _pg.admin_sql(
            self.db,
            f"""
            delete from evidence.outbox;
            delete from evidence.execution_events;
            delete from work.artifact_versions;
            delete from work.artifacts;
            delete from work.turns;
            delete from work.attempts;
            delete from work.tasks;
            delete from work.pending_items;
            delete from work.instance_transitions;
            delete from work.regions;
            delete from work.timers;
            delete from work.participants;
            delete from work.instances;
            delete from gov.budget_ledger;
            delete from gov.decision_records where event = 'admission.denied';
            update registry.seats set state = 'DRAFT', record_version = 1, configured_by = null, activated_by = null,
                pack_version_id = '{self.version_id}'
            where name = '{SEAT}';
            """,
        )

    def _activate_seat(self) -> None:
        async def _run() -> None:
            async with await psycopg.AsyncConnection.connect(_pg.kernel_url(self.db)) as conn:
                async with conn.transaction():
                    await insert_seats_for_published_pack(
                        conn, org=ORG, org_id=ORG.organization.id, pack_version_id=self.version_id
                    )

        asyncio.run(_run())
        seat = self.client.get(f"/api/console/seats/{SEAT}", headers=self._auth("platform_admin")).json()
        rv = seat["record_version"]
        if seat.get("state") == "DRAFT":
            configured = self.client.post(
                f"/api/console/seats/{SEAT}/configure",
                headers=self._auth("platform_admin"),
                json={"version": 1, "expected_version": rv},
            )
            self.assertEqual(configured.status_code, 200, configured.text)
            rv = configured.json()["record_version"]
        _pg.admin_sql(
            self.db,
            f"""
            update registry.seats
            set state = 'APPROVED', record_version = {rv}
            where org_id = 'org_demo' and name = '{SEAT}' and version = 1;
            insert into registry.eval_runs (id, org_id, seat, seat_version, suite, model, status, passed, total)
            values
              ('ev_worker_refusals', 'org_demo', '{SEAT}', 1, 'refusals', 'fake', 'passed', 4, 4),
              ('ev_worker_dry_run', 'org_demo', '{SEAT}', 1, 'dry_run', 'fake', 'passed', 1, 1)
            on conflict (id) do nothing;
            """,
        )
        r = self.client.post(
            f"/api/console/seats/{SEAT}/activate",
            headers=self._auth("head_of_procurement"),
            json={"version": 1, "expected_version": rv},
        )
        self.assertEqual(r.status_code, 200, r.text)

    def _start_job(self) -> str:
        self._activate_seat()
        r = self.client.post(
            "/api/instances",
            headers={**self._auth("faisal"), "Idempotency-Key": str(uuid.uuid4())},
            json={"seat": SEAT, "workflow": WORKFLOW, "first_message": "Worker API test"},
        )
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()["instance_id"]

    def _claim(self, worker_id: str = "worker-test-1") -> dict:
        r = self.client.post(
            "/api/worker/attempts/claim",
            headers=self.worker_auth(worker_id),
            json={"worker_id": worker_id, "lanes": ["assist"]},
        )
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _ledger_settled(self) -> float:
        out = _pg.admin_sql(
            self.db,
            f"select coalesce(settled_usd, 0) from gov.budget_ledger"
            f" where org_id = 'org_demo' and seat = '{SEAT}' and day = current_date;",
        ).stdout.strip()
        return float(out or 0)

    def _run_tick(self) -> int:
        async def tick() -> int:
            pool = AsyncConnectionPool(_pg.kernel_url(self.db), min_size=1, max_size=2, open=False)
            await pool.open(wait=True, timeout=15)
            try:
                return await run_lease_expiry_tick(pool, database_url=_pg.kernel_url(self.db))
            finally:
                await pool.close()

        return asyncio.run(tick())


@unittest.skipUnless(_pg.available(), "no local Postgres")
class WorkerApiTests(WorkerHarness):
    def test_worker_route_without_authorization_is_401(self) -> None:
        r = self.client.post(
            "/api/worker/attempts/claim",
            json={"worker_id": "w", "lanes": ["assist"]},
        )
        self.assertEqual(r.status_code, 401, r.text)

    def test_person_token_on_worker_route_is_401(self) -> None:
        r = self.client.post(
            "/api/worker/attempts/claim",
            headers=self._auth("faisal"),
            json={"worker_id": "x", "lanes": ["assist"]},
        )
        self.assertEqual(r.status_code, 401, r.text)

    def test_worker_token_on_instance_route_is_401(self) -> None:
        r = self.client.get("/api/instances", headers=self.worker_auth(), params={"participant": "me"})
        self.assertEqual(r.status_code, 401, r.text)

    def test_claim_body_worker_id_mismatch_is_403(self) -> None:
        r = self.client.post(
            "/api/worker/attempts/claim",
            headers=self.worker_auth("worker-a"),
            json={"worker_id": "worker-b", "lanes": ["assist"]},
        )
        self.assertEqual(r.status_code, 403, r.text)
        self.assertEqual(r.json()["code"], "not_permitted")

    def test_stale_fencing_token_commits_attempt_fenced(self) -> None:
        self._start_job()
        attempt = self._claim()
        old_token = attempt["fencing_token"]
        _pg.admin_sql(
            self.db,
            f"update work.tasks set fencing_token = fencing_token + 1"
            f" where id = '{attempt['task_id']}';",
        )
        r = self.client.post(
            f"/api/worker/attempts/{attempt['attempt_id']}/fail",
            headers={**self.worker_auth(), "X-AOS-Fencing-Token": str(old_token)},
            json={"failure_class": "internal", "message": "late fail"},
        )
        self.assertEqual(r.status_code, 409, r.text)
        self.assertEqual(r.json()["code"], "fenced")
        count = _pg.admin_sql(
            self.db,
            f"select count(*) from evidence.execution_events"
            f" where attempt_id = '{attempt['attempt_id']}' and event_type = 'AttemptFenced';",
        ).stdout.strip()
        self.assertEqual(count, "1")

    def test_expired_lease_readmits_and_late_heartbeat_is_fenced(self) -> None:
        self._start_job()
        attempt = self._claim()
        old_token = attempt["fencing_token"]
        _pg.admin_sql(
            self.db,
            f"update work.attempts set lease_expires_at = now() - interval '1 minute'"
            f" where id = '{attempt['attempt_id']}';",
        )

        n = self._run_tick()
        self.assertGreaterEqual(n, 1)

        new_token = _pg.admin_sql(
            self.db,
            f"select fencing_token from work.tasks where id = '{attempt['task_id']}';",
        ).stdout.strip()
        self.assertGreater(int(new_token), old_token)
        admitted = _pg.admin_sql(
            self.db,
            f"select count(*) from work.attempts where task_id = '{attempt['task_id']}' and state = 'ADMITTED';",
        ).stdout.strip()
        self.assertEqual(admitted, "1")

        hb = self.client.post(
            f"/api/worker/attempts/{attempt['attempt_id']}/heartbeat",
            headers={**self.worker_auth(), "X-AOS-Fencing-Token": str(old_token)},
        )
        self.assertEqual(hb.status_code, 409, hb.text)
        self.assertEqual(hb.json()["code"], "fenced")

    def test_final_failure_tells_the_participant(self) -> None:
        self._start_job()
        attempt = self._claim()
        r = self.client.post(
            f"/api/worker/attempts/{attempt['attempt_id']}/fail",
            headers={**self.worker_auth(), "X-AOS-Fencing-Token": str(attempt["fencing_token"])},
            json={"failure_class": "budget_exhausted", "message": "no steps left"},
        )
        self.assertEqual(r.status_code, 200, r.text)
        notices = _failure_notices(self.db)
        self.assertEqual(len(notices), 1, notices)
        self.assertIn("I couldn't finish this reply: I reached my limit", notices[0])
        self.assertNotIn("no steps left", notices[0])  # the worker's message stays in the events
        completed = _pg.admin_sql(
            self.db,
            "select count(*) from evidence.outbox where event_type = 'agent.message.completed';",
        ).stdout.strip()
        self.assertEqual(completed, "1")

    def test_retryable_failure_with_attempts_left_says_nothing_yet(self) -> None:
        self._start_job()
        attempt = self._claim()
        _pg.admin_sql(
            self.db,
            f"update work.tasks set max_attempts = 3 where id = '{attempt['task_id']}';",
        )
        r = self.client.post(
            f"/api/worker/attempts/{attempt['attempt_id']}/fail",
            headers={**self.worker_auth(), "X-AOS-Fencing-Token": str(attempt["fencing_token"])},
            json={"failure_class": "model_error", "message": "provider 500"},
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(_failure_notices(self.db), [])

    def test_expired_lease_with_no_attempts_left_tells_the_participant(self) -> None:
        self._start_job()
        attempt = self._claim()
        _pg.admin_sql(
            self.db,
            f"update work.tasks set max_attempts = attempts_used where id = '{attempt['task_id']}';"
            f" update work.attempts set lease_expires_at = now() - interval '1 minute'"
            f" where id = '{attempt['attempt_id']}';",
        )
        self._run_tick()
        notices = _failure_notices(self.db)
        self.assertEqual(len(notices), 1, notices)
        self.assertIn("I stopped responding", notices[0])

    def test_fail_racing_expiry_settles_budget_once(self) -> None:
        self._start_job()
        attempt = self._claim()
        _pg.admin_sql(
            self.db,
            f"update work.attempts set lease_expires_at = now() - interval '1 minute'"
            f" where id = '{attempt['attempt_id']}';",
        )
        settled_before = self._ledger_settled()
        barrier = threading.Barrier(2)
        results: dict[str, int] = {}

        def fail_worker() -> None:
            barrier.wait()
            r = self.client.post(
                f"/api/worker/attempts/{attempt['attempt_id']}/fail",
                headers={**self.worker_auth(), "X-AOS-Fencing-Token": str(attempt["fencing_token"])},
                json={"failure_class": "model_error", "message": "race"},
            )
            results["fail"] = r.status_code

        def expire_worker() -> None:
            barrier.wait()

            results["expire"] = self._run_tick()

        t1 = threading.Thread(target=fail_worker)
        t2 = threading.Thread(target=expire_worker)
        t1.start()
        t2.start()
        t1.join(10)
        t2.join(10)
        self.assertIn(results["fail"], (200, 409))
        if results["fail"] == 200:
            self.assertEqual(results["expire"], 0)
        else:
            self.assertEqual(results["fail"], 409)
            self.assertGreaterEqual(results["expire"], 1)
        settled_after = self._ledger_settled()
        reservation = float(
            _pg.admin_sql(
                self.db,
                f"select reserved_usd from work.attempts where id = '{attempt['attempt_id']}';",
            ).stdout.strip()
        )
        delta = round(settled_after - settled_before, 4)
        self.assertIn(delta, {0.0, round(reservation, 4)})
        ended = _pg.admin_sql(
            self.db,
            f"select count(*) from work.attempts where id = '{attempt['attempt_id']}' and state = 'ENDED';",
        ).stdout.strip()
        self.assertEqual(ended, "1")

    def test_scheduler_tick_noop_when_advisory_lock_held(self) -> None:
        async def run() -> int:
            pool = AsyncConnectionPool(_pg.kernel_url(self.db), min_size=1, max_size=2, open=False)
            await pool.open(wait=True, timeout=15)
            holder = await psycopg.AsyncConnection.connect(_pg.kernel_url(self.db), autocommit=True)
            await holder.execute("select pg_advisory_lock(%s)", (ADVISORY_LOCK_KEY,))
            try:
                return await run_lease_expiry_tick(pool, database_url=_pg.kernel_url(self.db))
            finally:
                await holder.execute("select pg_advisory_unlock(%s)", (ADVISORY_LOCK_KEY,))
                await holder.close()
                await pool.close()

        self.assertEqual(asyncio.run(run()), 0)

    def test_readmit_skipped_when_post_turn_already_admitted(self) -> None:
        inst_id = self._start_job()
        attempt = self._claim()
        _pg.admin_sql(
            self.db,
            f"update work.attempts set lease_expires_at = now() - interval '1 minute'"
            f" where id = '{attempt['attempt_id']}';",
        )

        async def expire_only():
            pool = AsyncConnectionPool(_pg.kernel_url(self.db), min_size=1, max_size=2, open=False)
            await pool.open(wait=True, timeout=15)
            try:
                async with pool.connection() as conn:
                    async with conn.transaction():
                        return await expire_one_attempt(conn)
            finally:
                await pool.close()

        outcome = asyncio.run(expire_only())
        self.assertTrue(outcome.expired)
        assert outcome.readmit is not None

        turn = self.client.post(
            f"/api/instances/{inst_id}/turns",
            headers=self._auth("faisal"),
            json={"text": "Follow-up before scheduler readmit", "client_turn_id": "readmit-race"},
        )
        self.assertEqual(turn.status_code, 202, turn.text)

        async def readmit():
            pool = AsyncConnectionPool(_pg.kernel_url(self.db), min_size=1, max_size=2, open=False)
            await pool.open(wait=True, timeout=15)
            try:
                async with pool.connection() as conn:
                    async with conn.transaction():
                        await readmit_after_expiry_lease(conn, outcome.readmit)
            finally:
                await pool.close()

        asyncio.run(readmit())

        live = _pg.admin_sql(
            self.db,
            f"select count(*) from work.attempts where task_id = '{attempt['task_id']}'"
            f" and state in ('ADMITTED', 'CLAIMED');",
        ).stdout.strip()
        self.assertEqual(live, "1")
        dr = _pg.admin_sql(
            self.db,
            "select count(*) from gov.decision_records where event = 'admission.denied' and value = 'conflict';",
        ).stdout.strip()
        self.assertEqual(dr, "1")

    def test_settlement_uses_admitted_at_day_not_today(self) -> None:
        self._start_job()
        attempt = self._claim()
        reserved = float(
            _pg.admin_sql(
                self.db,
                f"select reserved_usd from work.attempts where id = '{attempt['attempt_id']}';",
            ).stdout.strip()
        )
        _pg.admin_sql(
            self.db,
            f"""
            update work.attempts set admitted_at = (current_date - 1)::timestamptz + time '12:00'
            where id = '{attempt['attempt_id']}';
            delete from gov.budget_ledger where org_id = 'org_demo' and seat = '{SEAT}' and day = current_date;
            insert into gov.budget_ledger (org_id, seat, day, limit_usd, reserved_usd, settled_usd)
            values ('org_demo', '{SEAT}', current_date - 1, 100, {reserved}, 0)
            on conflict (org_id, seat, day) do update set reserved_usd = {reserved}, settled_usd = 0;
            """,
        )
        r = self.client.post(
            f"/api/worker/attempts/{attempt['attempt_id']}/fail",
            headers={**self.worker_auth(), "X-AOS-Fencing-Token": str(attempt["fencing_token"])},
            json={"failure_class": "internal", "message": "yesterday settle"},
        )
        self.assertEqual(r.status_code, 200, r.text)
        yesterday_reserved = _pg.admin_sql(
            self.db,
            f"select reserved_usd from gov.budget_ledger"
            f" where org_id = 'org_demo' and seat = '{SEAT}' and day = current_date - 1;",
        ).stdout.strip()
        today_row = _pg.admin_sql(
            self.db,
            f"select count(*) from gov.budget_ledger"
            f" where org_id = 'org_demo' and seat = '{SEAT}' and day = current_date;",
        ).stdout.strip()
        self.assertEqual(today_row, "0")
        self.assertEqual(float(yesterday_reserved), 0.0)

    def test_scheduler_tick_records_refusal_and_continues_on_second_expiry(self) -> None:
        self._start_job()
        self._start_job()
        a1 = self._claim("worker-a")
        a2 = self.client.post(
            "/api/worker/attempts/claim",
            headers=self.worker_auth("worker-b"),
            json={"worker_id": "worker-b", "lanes": ["assist"]},
        )
        self.assertEqual(a2.status_code, 200, a2.text)
        a2 = a2.json()
        _pg.admin_sql(
            self.db,
            f"""
            update work.attempts set lease_expires_at = now() - interval '1 minute'
            where id in ('{a1['attempt_id']}', '{a2['attempt_id']}');
            insert into gov.budget_ledger (org_id, seat, day, limit_usd, reserved_usd, settled_usd)
            values ('org_demo', '{SEAT}', current_date, 20, 20, 0)
            on conflict (org_id, seat, day) do update
            set reserved_usd = 20, settled_usd = 0, limit_usd = 20;
            """,
        )
        with patch("aos.kernel.admission._budget_fits", new_callable=AsyncMock, return_value=True):
            n = self._run_tick()
        self.assertEqual(n, 2)
        refusals = _pg.admin_sql(
            self.db,
            "select count(*) from gov.decision_records where event = 'admission.denied' and value = 'budget_exhausted';",
        ).stdout.strip()
        self.assertEqual(refusals, "2")

    def test_get_contract_returns_skill_instructions(self) -> None:
        self._start_job()
        attempt = self._claim()
        r = self.client.get(
            f"/api/worker/attempts/{attempt['attempt_id']}/contract",
            headers={**self.worker_auth(), "X-AOS-Fencing-Token": str(attempt["fencing_token"])},
        )
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertIn("contract", body)
        self.assertIn("skill_instructions", body)
        self.assertIn("Request intake", body["skill_instructions"])
        self.assertEqual(body["contract"]["skill"]["name"], "request_intake")


if __name__ == "__main__":
    unittest.main()
