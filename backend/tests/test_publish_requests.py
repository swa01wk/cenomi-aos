"""M1-BE-02: publish requests over HTTP against Postgres."""

from __future__ import annotations

import shutil
import tempfile
import unittest
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from aos.api import create_app
from aos.kernel.settings import REPO, Settings

from . import _pg


@unittest.skipUnless(_pg.available(), "no local Postgres")
class PublishRequestTests(unittest.TestCase):
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
        admin = cls.client.post("/api/auth/session", json={"person_id": "platform_admin"}).json()
        cls.admin_h = {"Authorization": f"Bearer {admin['token']}"}
        cls.version_id = cls.client.post(
            "/api/console/packs/procurement_demo/sync", headers=cls.admin_h, json={"source": "test"}
        ).json()["pack_version_id"]

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client.__exit__(None, None, None)
        _pg.drop(cls.db)
        shutil.rmtree(cls.packs, ignore_errors=True)

    def login(self, person: str) -> dict:
        token = self.client.post("/api/auth/session", json={"person_id": person}).json()["token"]
        return {"Authorization": f"Bearer {token}"}

    def open_request(self, *, requester: str = "platform_admin") -> dict:
        r = self.client.post(
            f"/api/console/pack-versions/{self.version_id}/publish-requests",
            headers=self.login(requester),
        )
        self.assertIn(r.status_code, (200, 201), r.text)
        return r.json()

    def audit_actions(self, headers: dict | None = None) -> list[str]:
        h = headers or self.login("risk")
        return [i["action"] for i in self.client.get("/api/console/audit?limit=500", headers=h).json()["items"]]

    def test_happy_path_publish(self) -> None:
        req = self.open_request()
        self.assertEqual(req["status"], "open")
        parts = {p["part"]: p for p in req["parts"]}
        self.assertEqual(parts["policies"]["role"], "risk")
        self.assertEqual(parts["seats_and_workflows"]["role"], "owner")

        listed = self.client.get("/api/console/publish-requests?status=open", headers=self.admin_h).json()["items"]
        self.assertTrue(any(i["id"] == req["id"] for i in listed))

        hop = self.login("head_of_procurement")
        risk = self.login("risk")
        r1 = self.client.post(
            f"/api/console/publish-requests/{req['id']}/approve",
            headers=risk,
            json={"part": "policies"},
        )
        self.assertEqual(r1.status_code, 200, r1.text)
        r2 = self.client.post(
            f"/api/console/publish-requests/{req['id']}/approve",
            headers=hop,
            json={"part": "seats_and_workflows"},
        )
        self.assertEqual(r2.status_code, 200, r2.text)
        self.assertEqual(r2.json()["status"], "approved")

        v = self.client.get(f"/api/console/pack-versions/{self.version_id}", headers=self.admin_h).json()
        self.assertEqual(v["status"], "published")
        actions = self.audit_actions()
        self.assertIn("pack.publish_requested", actions)
        self.assertIn("pack.publish_part_approved", actions)
        self.assertIn("pack.published", actions)

    def test_requester_cannot_approve(self) -> None:
        _pg.admin_sql(
            self.db,
            f"update registry.pack_versions set status = 'validated' where id = '{self.version_id}';"
            "delete from registry.publish_requests where pack_version_id = "
            f"'{self.version_id}';",
        )
        req = self.open_request()
        r = self.client.post(
            f"/api/console/publish-requests/{req['id']}/approve",
            headers=self.admin_h,
            json={"part": "policies"},
        )
        self.assertEqual(r.status_code, 403, r.text)
        self.assertEqual(r.json()["code"], "segregation_of_duties")

    def test_reject_closes_request_and_reverts_version(self) -> None:
        _pg.admin_sql(
            self.db,
            f"update registry.pack_versions set status = 'validated' where id = '{self.version_id}';"
            f"delete from registry.publish_requests where pack_version_id = '{self.version_id}';",
        )
        req = self.open_request()
        v_mid = self.client.get(f"/api/console/pack-versions/{self.version_id}", headers=self.admin_h).json()
        self.assertEqual(v_mid["status"], "publish_requested")

        r = self.client.post(
            f"/api/console/publish-requests/{req['id']}/reject",
            headers=self.login("risk"),
            json={"reason": "not ready yet"},
        )
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["status"], "rejected")
        self.assertTrue(all(p["status"] == "rejected" for p in body["parts"]))

        v = self.client.get(f"/api/console/pack-versions/{self.version_id}", headers=self.admin_h).json()
        self.assertEqual(v["status"], "validated")
        self.assertIn("pack.publish_rejected", self.audit_actions())

    def test_publish_twice_is_no_op(self) -> None:
        _pg.admin_sql(
            self.db,
            f"update registry.pack_versions set status = 'validated', published_at = null "
            f"where id = '{self.version_id}';"
            f"delete from registry.publish_requests where pack_version_id = '{self.version_id}';",
        )
        req = self.open_request()
        risk, hop = self.login("risk"), self.login("head_of_procurement")
        self.client.post(
            f"/api/console/publish-requests/{req['id']}/approve", headers=risk, json={"part": "policies"}
        )
        self.client.post(
            f"/api/console/publish-requests/{req['id']}/approve",
            headers=hop,
            json={"part": "seats_and_workflows"},
        )
        published_at = _pg.admin_sql(
            self.db,
            f"select published_at from registry.pack_versions where id = '{self.version_id}';",
        ).stdout.strip()
        published_count = self.audit_actions().count("pack.published")

        again = self.client.post(
            f"/api/console/publish-requests/{req['id']}/approve", headers=risk, json={"part": "policies"}
        )
        self.assertEqual(again.status_code, 200, again.text)
        published_at_again = _pg.admin_sql(
            self.db,
            f"select published_at from registry.pack_versions where id = '{self.version_id}';",
        ).stdout.strip()
        self.assertEqual(published_at_again, published_at)
        self.assertEqual(self.audit_actions().count("pack.published"), published_count)

    def test_requester_is_owner_refused(self) -> None:
        _pg.admin_sql(
            self.db,
            f"update registry.pack_versions set status = 'validated' where id = '{self.version_id}';"
            f"delete from registry.publish_requests where pack_version_id = '{self.version_id}';",
        )
        r = self.client.post(
            f"/api/console/pack-versions/{self.version_id}/publish-requests",
            headers=self.login("head_of_procurement"),
        )
        self.assertEqual(r.status_code, 403, r.text)
        self.assertEqual(r.json()["code"], "segregation_of_duties")

    def test_other_org_version_is_not_found(self) -> None:
        r = self.client.post(
            f"/api/console/pack-versions/{uuid.uuid4()}/publish-requests",
            headers=self.admin_h,
        )
        self.assertEqual(r.status_code, 404, r.text)
        self.assertEqual(r.json()["code"], "not_found")

        r2 = self.client.post(
            f"/api/console/publish-requests/{uuid.uuid4()}/reject",
            headers=self.login("risk"),
            json={"reason": "wrong id"},
        )
        self.assertEqual(r2.status_code, 404, r2.text)

    def test_repeat_request_by_same_caller_returns_open_request(self) -> None:
        _pg.admin_sql(
            self.db,
            f"update registry.pack_versions set status = 'validated' where id = '{self.version_id}';"
            f"delete from registry.publish_requests where pack_version_id = '{self.version_id}';",
        )
        first = self.client.post(
            f"/api/console/pack-versions/{self.version_id}/publish-requests",
            headers=self.admin_h,
        )
        self.assertEqual(first.status_code, 201, first.text)
        second = self.client.post(
            f"/api/console/pack-versions/{self.version_id}/publish-requests",
            headers=self.admin_h,
        )
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(first.json()["id"], second.json()["id"])

        conflict = self.client.post(
            f"/api/console/pack-versions/{self.version_id}/publish-requests",
            headers=self.login("risk"),
        )
        self.assertEqual(conflict.status_code, 409, conflict.text)
        self.assertEqual(conflict.json()["code"], "conflict")


if __name__ == "__main__":
    unittest.main()
