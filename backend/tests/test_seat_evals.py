"""M1-BE-03b: seat eval runs, strict gate and lifecycle integration."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from aos.api import create_app
from aos.kernel.org import load_org
from aos.kernel.seats import insert_seats_for_published_pack
from aos.kernel.settings import REPO, Settings

from . import _pg

ORG = load_org(REPO / "seed" / "org.yaml")

SEAT = "seat_sourcing_poc"
SEAT_DEF_VERSION = 1


@unittest.skipUnless(_pg.available(), "no local Postgres")
class SeatEvalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.db = _pg.create_migrated()
        cls.packs = Path(tempfile.mkdtemp(prefix="aos-packs-"))
        shutil.copytree(REPO / "packs" / "procurement_demo", cls.packs / "procurement_demo")
        cls._base_settings = Settings.from_env(
            database_url=_pg.kernel_url(cls.db),
            packs_dir=cls.packs,
            session_secret="test-secret-" + "x" * 40,
            eval_strict=False,
            eval_sync=True,
        )
        cls.client = TestClient(create_app(cls._base_settings))
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

    def setUp(self) -> None:
        _pg.admin_sql(
            self.db,
            f"""
            delete from registry.eval_runs where seat = '{SEAT}';
            delete from registry.seat_checks where seat = '{SEAT}';
            delete from registry.seat_events where seat = '{SEAT}';
            delete from gov.decision_records where subject_kind = 'seat' and subject_id = '{SEAT}';
            delete from evidence.outbox where event_type = 'seat.state_changed';
            delete from registry.seats where name = '{SEAT}' and version <> {SEAT_DEF_VERSION};
            update registry.seats
            set state = 'DRAFT', configured_by = null, activated_by = null,
                record_version = 1, updated_at = now()
            where name = '{SEAT}' and version = {SEAT_DEF_VERSION};
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

    def login(self, person: str) -> dict:
        return self._auth(person)

    def get_seat(self, person: str = "platform_admin") -> dict:
        return self.client.get(f"/api/console/seats/{SEAT}", headers=self.login(person)).json()

    def configure(self, person: str = "platform_admin") -> dict:
        seat = self.get_seat(person)
        return self.client.post(
            f"/api/console/seats/{SEAT}/configure",
            headers=self.login(person),
            json={"version": SEAT_DEF_VERSION, "expected_version": seat["record_version"]},
        ).json()

    def run_evals(self, person: str = "platform_admin", *, model: str = "fake") -> object:
        return self.client.post(
            f"/api/console/seats/{SEAT}/evals",
            headers=self.login(person),
            json={"version": SEAT_DEF_VERSION, "model": model},
        )

    def wait_for_evals(self) -> dict:
        for _ in range(50):
            seat = self.get_seat()
            evals = seat.get("evals") or []
            if evals and all(e["status"] != "running" for e in evals):
                return seat
        self.fail("eval runs did not finish")

    def approve(self, person: str, expected_version: int) -> object:
        return self.client.post(
            f"/api/console/seats/{SEAT}/approve",
            headers=self.login(person),
            json={"version": SEAT_DEF_VERSION, "expected_version": expected_version},
        )

    def activate(self, person: str, expected_version: int) -> object:
        return self.client.post(
            f"/api/console/seats/{SEAT}/activate",
            headers=self.login(person),
            json={"version": SEAT_DEF_VERSION, "expected_version": expected_version},
        )

    def test_run_evals_202_and_refusals_deferred_only(self) -> None:
        self.configure("platform_admin")
        r = self.run_evals()
        self.assertEqual(r.status_code, 202, r.text)
        body = r.json()
        self.assertEqual(len(body), 2)
        self.assertTrue(all(row["status"] == "running" for row in body))
        seat = self.wait_for_evals()
        refusals = next(e for e in seat["evals"] if e["suite"] == "refusals")
        self.assertEqual(refusals["status"], "passed")
        self.assertEqual(refusals["detail"]["deferred_count"], 2)
        self.assertTrue(all(x["status"] == "deferred" for x in refusals["detail"]["expectations"]))
        self.assertNotIn(
            "passed",
            {x["status"] for x in refusals["detail"]["expectations"]},
        )
        self.assertGreater(refusals["total"], 0)
        self.assertEqual(refusals["passed"], refusals["total"])

    def test_configure_to_testing_audit_and_outbox(self) -> None:
        configured = self.configure("platform_admin")
        self.assertEqual(configured["state"], "CONFIGURED")
        self.run_evals()
        seat = self.wait_for_evals()
        self.assertEqual(seat["state"], "TESTING")
        actions = [
            i["action"]
            for i in self.client.get("/api/console/audit?limit=500", headers=self.login("risk")).json()["items"]
        ]
        self.assertIn("seat.tested", actions)

    def test_full_happy_path_without_seed(self) -> None:
        configured = self.configure("platform_admin")
        self.run_evals()
        seat = self.wait_for_evals()
        self.assertEqual(seat["state"], "TESTING")
        r = self.approve("risk", seat["record_version"])
        self.assertEqual(r.status_code, 200, r.text)
        approved = r.json()
        act = self.activate("head_of_procurement", approved["record_version"])
        self.assertEqual(act.status_code, 200, act.text)
        self.assertEqual(act.json()["state"], "ACTIVE")

    def test_real_model_rejected(self) -> None:
        self.configure("platform_admin")
        r = self.run_evals(model="real")
        self.assertEqual(r.status_code, 422, r.text)
        self.assertEqual(r.json()["code"], "validation_failed")

    def test_stuck_run_409_and_interrupted(self) -> None:
        self.configure("platform_admin")
        _pg.admin_sql(
            self.db,
            f"""
            insert into registry.eval_runs (
              id, org_id, seat, seat_version, suite, model, status, passed, total, started_at
            )
            values (
              'ev_stuck', (select id from org.organizations limit 1), '{SEAT}', {SEAT_DEF_VERSION},
              'refusals', 'fake', 'running', 0, 0, now()
            );
            """,
        )
        r = self.run_evals()
        self.assertEqual(r.status_code, 409, r.text)
        _pg.admin_sql(
            self.db,
            f"""
            update registry.eval_runs
            set started_at = now() - interval '11 minutes'
            where id = 'ev_stuck';
            """,
        )
        r2 = self.run_evals()
        self.assertEqual(r2.status_code, 202, r2.text)
        row = _pg.admin_sql(
            self.db,
            "select status, detail from registry.eval_runs where id = 'ev_stuck'",
        ).stdout.strip()
        status, detail = row.split("|", 1)
        self.assertEqual(status, "failed")
        self.assertIn("interrupted", detail)

    def test_failed_rerun_blocks_approve(self) -> None:
        configured = self.configure("platform_admin")
        self.run_evals()
        seat = self.wait_for_evals()
        self.assertEqual(seat["state"], "TESTING")
        _pg.admin_sql(
            self.db,
            f"""
            insert into registry.eval_runs (
              id, org_id, seat, seat_version, suite, model, status, passed, total, detail, finished_at
            )
            values (
              'ev_fail_ref', (select id from org.organizations limit 1), '{SEAT}', {SEAT_DEF_VERSION},
              'refusals', 'fake', 'failed', 0, 1, '{{"deferred_count": 0}}', now()
            );
            """,
        )
        seat = self.get_seat()
        r = self.approve("risk", seat["record_version"])
        self.assertEqual(r.status_code, 409, r.text)

    def test_eval_strict_blocks_activate(self) -> None:
        strict_settings = Settings.from_env(
            database_url=_pg.kernel_url(self.db),
            packs_dir=self.packs,
            session_secret="test-secret-" + "x" * 40,
            eval_strict=True,
            eval_sync=True,
        )
        with TestClient(create_app(strict_settings)) as strict_client:
            def auth(person: str) -> dict:
                token = strict_client.post("/api/auth/session", json={"person_id": person}).json()["token"]
                return {"Authorization": f"Bearer {token}"}

            seat = strict_client.get(f"/api/console/seats/{SEAT}", headers=auth("platform_admin")).json()
            strict_client.post(
                f"/api/console/seats/{SEAT}/configure",
                headers=auth("platform_admin"),
                json={"version": SEAT_DEF_VERSION, "expected_version": seat["record_version"]},
            )
            strict_client.post(
                f"/api/console/seats/{SEAT}/evals",
                headers=auth("platform_admin"),
                json={"version": SEAT_DEF_VERSION, "model": "fake"},
            )
            for _ in range(50):
                seat = strict_client.get(f"/api/console/seats/{SEAT}", headers=auth("platform_admin")).json()
                if seat["state"] == "TESTING":
                    break
            approved = strict_client.post(
                f"/api/console/seats/{SEAT}/approve",
                headers=auth("risk"),
                json={"version": SEAT_DEF_VERSION, "expected_version": seat["record_version"]},
            ).json()
            r = strict_client.post(
                f"/api/console/seats/{SEAT}/activate",
                headers=auth("head_of_procurement"),
                json={"version": SEAT_DEF_VERSION, "expected_version": approved["record_version"]},
            )
            self.assertEqual(r.status_code, 409, r.text)
            problem = r.json()
            self.assertEqual(problem["code"], "conflict")
            self.assertIn("deferred", problem["title"].lower() + problem["detail"].lower())

    def test_run_evals_forbidden_role(self) -> None:
        self.configure("platform_admin")
        r = self.client.post(
            f"/api/console/seats/{SEAT}/evals",
            headers=self.login("risk"),
            json={"version": SEAT_DEF_VERSION, "model": "fake"},
        )
        self.assertEqual(r.status_code, 403, r.text)

    def test_activate_unique_violation_same_409(self) -> None:
        configured = self.configure("platform_admin")
        self.run_evals()
        seat = self.wait_for_evals()
        r = self.approve("risk", seat["record_version"])
        approved = r.json()
        _pg.admin_sql(
            self.db,
            f"""
            insert into registry.seats (
              org_id, name, version, pack_version_id, display_name, placement, owner_person_id, state
            )
            select org_id, name, 2, pack_version_id, display_name, placement, owner_person_id, 'ACTIVE'
            from registry.seats where name = '{SEAT}' and version = {SEAT_DEF_VERSION};
            """,
        )
        with patch("aos.kernel.seats._find_other_live_seat", new=AsyncMock(return_value=None)):
            act = self.activate("head_of_procurement", approved["record_version"])
        self.assertEqual(act.status_code, 409, act.text)
        self.assertEqual(act.json()["code"], "conflict")
        self.assertIn("retire", act.json()["detail"].lower())


if __name__ == "__main__":
    unittest.main()
