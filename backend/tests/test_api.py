"""M0 kernel API against a real, freshly migrated Postgres database.

Covers persona sign-in, the Console gate, org read-back, pack validate and sync (idempotent, version
pinning), definition read-back, and the audit chain over HTTP including tamper detection.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from aos.api import create_app
from aos.kernel.settings import REPO, Settings

from . import _pg


@unittest.skipUnless(_pg.available(), "no local Postgres")
class KernelApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.db = _pg.create_migrated()
        cls.packs = Path(tempfile.mkdtemp(prefix="aos-packs-"))
        shutil.copytree(REPO / "packs" / "procurement_demo", cls.packs / "procurement_demo")
        settings = Settings.from_env(database_url=_pg.kernel_url(cls.db), packs_dir=cls.packs,
                                     session_secret="test-secret-" + "x" * 40)
        cls.client = TestClient(create_app(settings))
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client.__exit__(None, None, None)
        _pg.drop(cls.db)
        shutil.rmtree(cls.packs, ignore_errors=True)

    def login(self, person: str) -> dict:
        r = self.client.post("/api/auth/session", json={"person_id": person})
        self.assertEqual(r.status_code, 200, r.text)
        return {"Authorization": f"Bearer {r.json()['token']}"}

    # ---------------------------------------------------------------- sign-in and the Console gate

    def test_health_and_personas(self) -> None:
        self.assertEqual(self.client.get("/api/healthz").json(), {"status": "ok"})
        ids = {p["id"] for p in self.client.get("/api/auth/personas").json()}
        self.assertTrue({"noura", "khalid", "faisal", "platform_admin", "risk"} <= ids)

    def test_session_and_me(self) -> None:
        me = self.client.get("/api/me", headers=self.login("noura")).json()
        self.assertEqual((me["id"], me["org"], me["console"]), ("noura", "org_demo", False))
        self.assertEqual(self.client.get("/api/me").status_code, 401)
        self.assertEqual(self.client.get("/api/me", headers={"Authorization": "Bearer junk"}).status_code, 401)
        self.assertEqual(self.client.post("/api/auth/session", json={"person_id": "mallory"}).status_code, 404)

    def test_workspace_people_cannot_reach_the_console(self) -> None:
        for person in ("noura", "faisal"):
            r = self.client.get("/api/console/packs", headers=self.login(person))
            self.assertEqual(r.status_code, 403, person)

    def test_risk_can_read_packs_but_not_sync(self) -> None:
        h = self.login("risk")
        self.assertEqual(self.client.get("/api/console/packs", headers=h).status_code, 200)
        self.assertEqual(self.client.post("/api/console/packs/procurement_demo/sync", headers=h).status_code, 403)

    # ---------------------------------------------------------------- organization

    def test_org_reads_back_the_seed(self) -> None:
        org = self.client.get("/api/org", headers=self.login("noura")).json()
        self.assertEqual(org["organization"]["id"], "org_demo")
        procurement = next(d for d in org["departments"] if d["id"] == "procurement")
        self.assertEqual({t["id"] for t in procurement["teams"]}, {"sourcing", "procurement"})
        hop = next(p for p in org["people"] if p["id"] == "head_of_procurement")
        self.assertEqual(hop["roles"], ["process_owner", "seat_owner"])

    # ---------------------------------------------------------------- packs

    def test_validate_endpoint_matches_cli(self) -> None:
        r = self.client.post("/api/console/packs/procurement_demo/validate", headers=self.login("platform_admin"))
        body = r.json()
        self.assertTrue(body["ok"], body["errors"])
        self.assertEqual(body["counts"]["Seat"], 1)
        self.assertEqual(self.client.post("/api/console/packs/../seed/validate",
                                          headers=self.login("platform_admin")).status_code, 404)

    def test_sync_is_idempotent_and_stores_definitions(self) -> None:
        h = self.login("head_of_procurement")
        first = self.client.post("/api/console/packs/procurement_demo/sync", headers=h, json={"source": "test"}).json()
        again = self.client.post("/api/console/packs/procurement_demo/sync", headers=h).json()
        self.assertEqual(first["pack_version_id"], again["pack_version_id"])
        self.assertEqual(first["status"], "validated")
        self.assertFalse(again["created"])

        v = self.client.get(f"/api/console/pack-versions/{first['pack_version_id']}", headers=h).json()
        kinds = {d["kind"] for d in v["definitions"]}
        self.assertTrue({"Pack", "Seat", "Skill", "WorkflowDefinition", "Policy"} <= kinds)
        seat = self.client.get(f"/api/console/pack-versions/{first['pack_version_id']}/definitions/Seat/"
                               "seat_sourcing_poc", headers=h).json()
        self.assertEqual(seat["metadata"]["name"], "seat_sourcing_poc")

        listing = self.client.get("/api/console/packs", headers=h).json()
        self.assertIn("procurement_demo", listing["available"])
        self.assertEqual(listing["packs"][0]["owner"], "head_of_procurement")

    def test_published_version_number_is_taken(self) -> None:
        h = self.login("platform_admin")
        first = self.client.post("/api/console/packs/procurement_demo/sync", headers=h).json()
        _pg.admin_sql(self.db, f"update registry.pack_versions set status = 'published' "
                               f"where id = '{first['pack_version_id']}';")
        pack_yaml = self.packs / "procurement_demo" / "pack.yaml"
        original = pack_yaml.read_text()
        try:
            pack_yaml.write_text(original.replace("Quick Quote on", "Quick Quote (edited) on"))
            r = self.client.post("/api/console/packs/procurement_demo/sync", headers=h)
            self.assertEqual(r.status_code, 409)
            self.assertIn("bump metadata.version", r.json()["detail"])
        finally:
            pack_yaml.write_text(original)
            _pg.admin_sql(self.db, "alter table registry.definitions disable trigger definitions_immutable;"
                                   f"update registry.pack_versions set status = 'validated' "
                                   f"where id = '{first['pack_version_id']}';"
                                   "alter table registry.definitions enable trigger definitions_immutable;")

    def test_invalid_pack_is_stored_as_invalid(self) -> None:
        bad = self.packs / "broken_demo"
        shutil.copytree(self.packs / "procurement_demo", bad)
        (bad / "pack.yaml").write_text((bad / "pack.yaml").read_text().replace("procurement_demo", "broken_demo"))
        seat = next(bad.glob("seats/*.yaml"))
        seat.write_text(seat.read_text().replace("quote_comparison", "no_such_skill", 1))
        h = self.login("platform_admin")
        r = self.client.post("/api/console/packs/broken_demo/sync", headers=h).json()
        self.assertEqual(r["status"], "invalid")
        self.assertIn("E_REF", {e["code"] for e in r["report"]["errors"]})

    # ---------------------------------------------------------------- audit

    def test_actions_are_audited_and_the_chain_verifies(self) -> None:
        h = self.login("risk")
        items = self.client.get("/api/console/audit?limit=200", headers=h).json()["items"]
        actions = {i["action"] for i in items}
        self.assertIn("session.started", actions)
        seqs = [i["seq"] for i in items]
        self.assertEqual(seqs, sorted(seqs, reverse=True))
        report = self.client.post("/api/console/audit/verify", headers=h).json()
        self.assertTrue(report["intact"], report)
        self.assertEqual(self.client.get("/api/console/audit", headers=self.login("head_of_procurement")).status_code,
                         403)

    def test_tampering_is_detected_over_http(self) -> None:
        h = self.login("risk")
        scratch = _pg.create_migrated()
        try:
            settings = Settings.from_env(database_url=_pg.kernel_url(scratch), packs_dir=self.packs,
                                         session_secret="test-secret-" + "x" * 40)
            with TestClient(create_app(settings)) as c:
                h = {"Authorization": "Bearer " + c.post("/api/auth/session", json={"person_id": "risk"}).json()["token"]}
                for person in ("noura", "khalid", "faisal"):
                    c.post("/api/auth/session", json={"person_id": person})
                self.assertTrue(c.post("/api/console/audit/verify", headers=h).json()["intact"])
                _pg.admin_sql(scratch, "alter table evidence.audit_events disable trigger audit_append_only;"
                                       "update evidence.audit_events set actor = 'mallory' where seq = 3;"
                                       "alter table evidence.audit_events enable trigger audit_append_only;")
                report = c.post("/api/console/audit/verify", headers=h).json()
                self.assertFalse(report["intact"])
                self.assertEqual(report["first_broken_seq"], 3)
        finally:
            _pg.drop(scratch)


if __name__ == "__main__":
    unittest.main()
