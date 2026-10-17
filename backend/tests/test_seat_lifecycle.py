"""M1-BE-03a: seat lifecycle (no eval runner)."""

from __future__ import annotations

import asyncio
import shutil
import tempfile
import unittest
from pathlib import Path

import psycopg
from fastapi.testclient import TestClient

from aos.api import create_app
from aos.kernel.org import load_org
from aos.kernel.seats import ensure_registry_seats_for_pack
from aos.kernel.settings import REPO, Settings

from . import _pg

ORG = load_org(REPO / "seed" / "org.yaml")

SEAT = "seat_sourcing_poc"
SEAT_DEF_VERSION = 1


@unittest.skipUnless(_pg.available(), "no local Postgres")
class SeatLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.db = _pg.create_migrated()
        cls.packs = Path(tempfile.mkdtemp(prefix="aos-packs-"))
        shutil.copytree(REPO / "packs" / "procurement_demo", cls.packs / "procurement_demo")
        settings = Settings.from_env(
            database_url=_pg.kernel_url(cls.db),
            packs_dir=cls.packs,
            session_secret="test-secret-" + "x" * 40,
        )
        cls.client = TestClient(create_app(settings))
        cls.client.__enter__()
        cls.version_id = cls.client.post(
            "/api/console/packs/procurement_demo/sync",
            headers=cls._auth("platform_admin"),
            json={"source": "test"},
        ).json()["pack_version_id"]
        cls._publish_pack_once()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client.__exit__(None, None, None)
        _pg.drop(cls.db)
        shutil.rmtree(cls.packs, ignore_errors=True)

    @classmethod
    def _auth(cls, person: str) -> dict:
        token = cls.client.post("/api/auth/session", json={"person_id": person}).json()["token"]
        return {"Authorization": f"Bearer {token}"}

    def login(self, person: str) -> dict:
        return self._auth(person)

    def setUp(self) -> None:
        _pg.admin_sql(
            self.db,
            f"""
            delete from registry.eval_runs where seat = '{SEAT}';
            delete from registry.seat_checks where seat = '{SEAT}';
            delete from registry.seat_events where seat = '{SEAT}';
            delete from gov.decision_records where subject_kind = 'seat' and subject_id = '{SEAT}';
            delete from evidence.outbox where event_type = 'seat.state_changed';
            update registry.seats
            set state = 'DRAFT', configured_by = null, activated_by = null,
                record_version = 1, updated_at = now()
            where name = '{SEAT}';
            update registry.pack_versions set status = 'published' where id = '{self.version_id}';
            """,
        )

    @classmethod
    def _publish_pack_once(cls) -> None:
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

    def ensure_seats(self) -> None:
        async def _run() -> None:
            async with await psycopg.AsyncConnection.connect(_pg.kernel_url(self.db)) as conn:
                async with conn.transaction():
                    await ensure_registry_seats_for_pack(
                        conn,
                        org=ORG,
                        org_id=ORG.organization.id,
                        pack_version_id=self.version_id,
                    )

        asyncio.run(_run())

    def get_seat(self, person: str = "platform_admin") -> dict:
        return self.client.get(f"/api/console/seats/{SEAT}", headers=self.login(person)).json()

    def configure(self, person: str = "platform_admin") -> dict:
        seat = self.get_seat(person)
        return self.client.post(
            f"/api/console/seats/{SEAT}/configure",
            headers=self.login(person),
            json={"version": SEAT_DEF_VERSION, "expected_version": seat["record_version"]},
        ).json()

    def seed_approved_with_evals(self, *, record_version: int) -> None:
        _pg.admin_sql(
            self.db,
            f"""
            update registry.seats
            set state = 'APPROVED', record_version = {record_version}
            where org_id = (select id from org.organizations limit 1)
              and name = '{SEAT}' and version = {SEAT_DEF_VERSION};
            insert into registry.eval_runs (id, org_id, seat, seat_version, suite, model, status, passed, total)
            values
              ('ev_test_refusals', (select id from org.organizations limit 1), '{SEAT}', {SEAT_DEF_VERSION},
               'refusals', 'fake', 'passed', 4, 4),
              ('ev_test_dry_run', (select id from org.organizations limit 1), '{SEAT}', {SEAT_DEF_VERSION},
               'dry_run', 'fake', 'passed', 1, 1)
            on conflict (id) do nothing;
            """,
        )

    def activate(self, person: str, expected_version: int) -> object:
        return self.client.post(
            f"/api/console/seats/{SEAT}/activate",
            headers=self.login(person),
            json={"version": SEAT_DEF_VERSION, "expected_version": expected_version},
        )

    def approve(self, person: str, expected_version: int) -> object:
        return self.client.post(
            f"/api/console/seats/{SEAT}/approve",
            headers=self.login(person),
            json={"version": SEAT_DEF_VERSION, "expected_version": expected_version},
        )

    def test_publish_creates_draft_seats(self) -> None:
        _pg.admin_sql(self.db, f"delete from registry.seats where name = '{SEAT}'")
        self.ensure_seats()
        raw = _pg.admin_sql(
            self.db,
            f"select name, version, state from registry.seats where name = '{SEAT}'",
        ).stdout.strip()
        rows = [line.split("|") for line in raw.splitlines() if line]
        self.assertEqual(len(rows), 1)
        self.assertEqual(int(rows[0][1]), SEAT_DEF_VERSION)
        self.assertEqual(rows[0][2], "DRAFT")

    def test_configure_pass_to_configured(self) -> None:
        body = self.configure("platform_admin")
        self.assertEqual(body["state"], "CONFIGURED")
        self.assertEqual(body["configured_by"], "platform_admin")
        self.assertTrue(all(c["passed"] for c in body["checks"]))

    def test_configure_fail_stays_draft(self) -> None:
        _pg.admin_sql(
            self.db,
            f"update registry.pack_versions set status = 'validated' where id = '{self.version_id}'",
        )
        seat = self.get_seat()
        body = self.client.post(
            f"/api/console/seats/{SEAT}/configure",
            headers=self.login("platform_admin"),
            json={"version": SEAT_DEF_VERSION, "expected_version": seat["record_version"]},
        ).json()
        self.assertEqual(body["state"], "DRAFT")
        failed = [c for c in body["checks"] if not c["passed"]]
        self.assertTrue(any(c["name"] == "pack_version_published" for c in failed))

    def test_configurer_activate_denied_with_audit_and_dr(self) -> None:
        configured = self.configure("head_of_procurement")
        self.seed_approved_with_evals(record_version=configured["record_version"])
        r = self.activate("head_of_procurement", configured["record_version"])
        self.assertEqual(r.status_code, 403, r.text)
        problem = r.json()
        self.assertEqual(problem["code"], "segregation_of_duties")
        self.assertIn("decision_id", problem)
        dr = _pg.admin_sql(
            self.db,
            f"select value from gov.decision_records where id = '{problem['decision_id']}'",
        ).stdout.strip()
        self.assertEqual(dr, "DENY")
        seat_state = _pg.admin_sql(
            self.db,
            f"select state from registry.seats where name = '{SEAT}' and version = {SEAT_DEF_VERSION}",
        ).stdout.strip()
        self.assertEqual(seat_state, "APPROVED")
        actions = [
            i["action"]
            for i in self.client.get("/api/console/audit?limit=500", headers=self.login("risk")).json()["items"]
        ]
        self.assertIn("seat.activate.denied", actions)

    def test_non_owner_activate_not_permitted(self) -> None:
        configured = self.configure("platform_admin")
        self.seed_approved_with_evals(record_version=configured["record_version"])
        r = self.activate("risk", configured["record_version"])
        self.assertEqual(r.status_code, 403, r.text)
        self.assertEqual(r.json()["code"], "not_permitted")
        self.assertIn("decision_id", r.json())

    def test_owner_activation_active_and_outbox(self) -> None:
        configured = self.configure("platform_admin")
        self.seed_approved_with_evals(record_version=configured["record_version"])
        r = self.activate("head_of_procurement", configured["record_version"])
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["state"], "ACTIVE")
        self.assertEqual(body["availability"], "AVAILABLE")
        raw = _pg.admin_sql(
            self.db,
            "select stream from evidence.outbox where event_type = 'seat.state_changed'",
        ).stdout.strip()
        streams = set(raw.splitlines()) if raw else set()
        self.assertIn("user:head_of_procurement", streams)
        self.assertIn("user:noura", streams)

    def test_approve_from_configured_conflict(self) -> None:
        configured = self.configure("platform_admin")
        r = self.approve("risk", configured["record_version"])
        self.assertEqual(r.status_code, 409, r.text)
        self.assertEqual(r.json()["code"], "conflict")

    def test_stale_expected_version(self) -> None:
        seat = self.get_seat()
        r = self.client.post(
            f"/api/console/seats/{SEAT}/configure",
            headers=self.login("platform_admin"),
            json={"version": SEAT_DEF_VERSION, "expected_version": seat["record_version"] - 1},
        )
        self.assertEqual(r.status_code, 409, r.text)
        self.assertEqual(r.json()["code"], "stale_version")
        self.assertEqual(r.json()["current_version"], seat["record_version"])


if __name__ == "__main__":
    unittest.main()
