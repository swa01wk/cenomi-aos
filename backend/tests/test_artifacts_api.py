"""HTTP tests for artifact reads and snapshot projection (M1-BE-04 C)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import psycopg
from fastapi.testclient import TestClient

from aos.api import create_app
from aos.kernel import ids
from aos.kernel.contracts import _canonical_json
from aos.kernel.org import load_org
from aos.kernel.seats import insert_seats_for_published_pack
from aos.kernel.settings import REPO, Settings

from . import _pg

ORG = load_org(REPO / "seed" / "org.yaml")
SEAT = "seat_sourcing_poc"
WORKFLOW = "quick_quote"
PLANT_PRICE = "SAR 88888.01"


@unittest.skipUnless(_pg.available(), "no local Postgres")
class ArtifactsApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.db = _pg.create_migrated()
        cls.packs = Path(tempfile.mkdtemp(prefix="aos-packs-artifacts-"))
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

    def login(self, person: str) -> dict:
        return self._auth(person)

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

    def _ensure_seats(self) -> None:
        async def _run() -> None:
            async with await psycopg.AsyncConnection.connect(_pg.kernel_url(self.db)) as conn:
                async with conn.transaction():
                    await insert_seats_for_published_pack(
                        conn, org=ORG, org_id=ORG.organization.id, pack_version_id=self.version_id
                    )

        asyncio.run(_run())

    def _activate_seat(self) -> None:
        self._ensure_seats()
        seat = self.client.get(f"/api/console/seats/{SEAT}", headers=self.login("platform_admin")).json()
        configured = self.client.post(
            f"/api/console/seats/{SEAT}/configure",
            headers=self.login("platform_admin"),
            json={"version": 1, "expected_version": seat["record_version"]},
        ).json()
        rv = configured["record_version"]
        _pg.admin_sql(
            self.db,
            f"""
            update registry.seats
            set state = 'APPROVED', record_version = {rv}
            where org_id = (select id from org.organizations limit 1)
              and name = '{SEAT}' and version = 1;
            insert into registry.eval_runs (id, org_id, seat, seat_version, suite, model, status, passed, total)
            values
              ('ev_art_refusals', (select id from org.organizations limit 1), '{SEAT}', 1,
               'refusals', 'fake', 'passed', 4, 4),
              ('ev_art_dry_run', (select id from org.organizations limit 1), '{SEAT}', 1,
               'dry_run', 'fake', 'passed', 1, 1)
            on conflict (id) do nothing;
            """,
        )
        r = self.client.post(
            f"/api/console/seats/{SEAT}/activate",
            headers=self.login("head_of_procurement"),
            json={"version": 1, "expected_version": rv},
        )
        self.assertEqual(r.status_code, 200, r.text)

    def _start(self, person: str = "faisal") -> str:
        r = self.client.post(
            "/api/instances",
            headers=self.login(person),
            json={"seat": SEAT, "workflow": WORKFLOW, "first_message": "Need trolleys"},
        )
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()["instance_id"]

    def _insert_comparison(self, instance_id: str) -> tuple[str, str]:
        art_id = ids.new_artifact_id()
        content = {
            "rows": [
                {
                    "rank": 1,
                    "supplier": "Najd Supplies",
                    "unit_price": PLANT_PRICE,
                    "total": PLANT_PRICE,
                    "lead_time_days": 14,
                    "warranty_months": 12,
                    "score": 88.5,
                }
            ]
        }
        full_hash = hashlib.sha256(_canonical_json(content)).hexdigest()
        verification = json.dumps(
            {
                "verifier": "price_check",
                "verdict": "PASS",
                "findings": [f"Totals include {PLANT_PRICE} per line"],
            }
        )
        sources = json.dumps([{"source_ref": "mail:q1", "label": "Quote mail", "body": PLANT_PRICE}])
        _pg.admin_sql(
            self.db,
            f"""
            insert into work.artifacts (id, instance_id, artifact_type, key, name, status, latest_version)
            values ('{art_id}', '{instance_id}', 'comparison', '', 'Quote comparison', 'draft', 1);
            insert into work.artifact_versions (
              artifact_id, version, content, content_hash, produced_by_kind, produced_by,
              inputs, sources, verification
            ) values (
              '{art_id}', 1, '{json.dumps(content)}'::jsonb, '{full_hash}', 'person', 'noura',
              '[]'::jsonb, '{sources}'::jsonb, '{verification}'::jsonb
            );
            """,
        )
        return art_id, full_hash

    def setUp(self) -> None:
        _pg.admin_sql(
            self.db,
            """
            delete from work.artifact_versions;
            delete from work.artifacts;
            delete from evidence.outbox;
            delete from evidence.execution_events;
            delete from work.turns;
            delete from work.attempts;
            delete from work.tasks;
            delete from work.participants;
            delete from work.instances;
            delete from gov.budget_ledger;
            update registry.seats set state = 'DRAFT', record_version = 1, configured_by = null, activated_by = null,
                pack_version_id = '%s'
            where name = 'seat_sourcing_poc';
            """
            % self.version_id,
        )

    def test_leak_free_for_requester_across_endpoints(self) -> None:
        self._activate_seat()
        instance_id = self._start("faisal")
        art_id, full_hash = self._insert_comparison(instance_id)

        snap = self.client.get(f"/api/instances/{instance_id}", headers=self.login("faisal"))
        self.assertEqual(snap.status_code, 200, snap.text)
        summary = self.client.get(f"/api/artifacts/{art_id}", headers=self.login("faisal"))
        self.assertEqual(summary.status_code, 200, summary.text)
        version = self.client.get(f"/api/artifacts/{art_id}/versions/1", headers=self.login("faisal"))
        self.assertEqual(version.status_code, 200, version.text)

        for label, body in (
            ("snapshot", snap.text),
            ("getArtifact", summary.text),
            ("getArtifactVersion", version.text),
        ):
            self.assertNotIn(PLANT_PRICE, body, msg=label)
            self.assertNotIn(full_hash, body, msg=label)

        ver = version.json()
        self.assertNotIn("content_hash", ver)
        self.assertIn("projected_content_hash", ver)
        self.assertIn("unit_price", ver["hidden_fields"])
        self.assertNotIn("findings", json.dumps(ver.get("verification", {})))

        arts = snap.json()["artifacts"]
        self.assertEqual(len(arts), 1)
        cols = arts[0]["view"].get("columns", [])
        self.assertNotIn("unit_price", cols)

    def _bind_buyer(self, instance_id: str, person: str = "noura") -> None:
        _pg.admin_sql(
            self.db,
            f"""
            insert into work.participants (instance_id, role, person_id, bound_by)
            values ('{instance_id}', 'buyer', '{person}', 'rule')
            on conflict (instance_id, role) do update set person_id = excluded.person_id;
            """,
        )

    def test_buyer_sees_price_and_findings(self) -> None:
        self._activate_seat()
        instance_id = self._start("faisal")
        art_id, full_hash = self._insert_comparison(instance_id)
        self._bind_buyer(instance_id)

        version = self.client.get(f"/api/artifacts/{art_id}/versions/1", headers=self.login("noura"))
        self.assertEqual(version.status_code, 200, version.text)
        ver = version.json()
        self.assertIn(PLANT_PRICE, version.text)
        self.assertEqual(ver["content_hash"], full_hash)
        self.assertNotIn("projected_content_hash", ver)
        self.assertEqual(ver["hidden_fields"], [])
        self.assertIn("findings", json.dumps(ver["verification"]))

    def test_non_participant_forbidden(self) -> None:
        self._activate_seat()
        instance_id = self._start("faisal")
        art_id, _ = self._insert_comparison(instance_id)
        r = self.client.get(f"/api/artifacts/{art_id}", headers=self.login("platform_admin"))
        self.assertEqual(r.status_code, 403, r.text)
        self.assertEqual(r.json()["code"], "not_permitted")

    def test_unknown_artifact_not_found(self) -> None:
        self._activate_seat()
        self._start("faisal")
        r = self.client.get(f"/api/artifacts/{ids.new_artifact_id()}", headers=self.login("faisal"))
        self.assertEqual(r.status_code, 404, r.text)


if __name__ == "__main__":
    unittest.main()
