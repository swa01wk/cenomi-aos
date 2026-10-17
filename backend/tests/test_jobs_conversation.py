"""M1-BE-04 (PR A): jobs, admission and conversation commands."""

from __future__ import annotations

import asyncio
import shutil
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import psycopg
from fastapi.testclient import TestClient

from aos.api import create_app
from aos.kernel import ids
from aos.kernel.org import load_org
from aos.kernel.seats import insert_seats_for_published_pack
from aos.kernel.settings import REPO, Settings

from . import _pg

ORG = load_org(REPO / "seed" / "org.yaml")
SEAT = "seat_sourcing_poc"
WORKFLOW = "quick_quote"


@unittest.skipUnless(_pg.available(), "no local Postgres")
class JobsConversationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.db = _pg.create_migrated()
        cls.packs = Path(tempfile.mkdtemp(prefix="aos-packs-jobs-"))
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
              ('ev_jobs_refusals', (select id from org.organizations limit 1), '{SEAT}', 1,
               'refusals', 'fake', 'passed', 4, 4),
              ('ev_jobs_dry_run', (select id from org.organizations limit 1), '{SEAT}', 1,
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

    def _start(
        self,
        person: str = "faisal",
        *,
        idempotency_key: str | None = None,
        message: str = "Need cleaning trolleys for the mall",
    ) -> object:
        headers = self.login(person)
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return self.client.post(
            "/api/instances",
            headers=headers,
            json={"seat": SEAT, "workflow": WORKFLOW, "first_message": message},
        )

    def setUp(self) -> None:
        _pg.admin_sql(
            self.db,
            """
            delete from evidence.outbox;
            delete from evidence.execution_events;
            delete from work.turns;
            delete from work.attempts;
            delete from work.tasks;
            delete from work.participants;
            delete from work.instances;
            delete from gov.budget_ledger;
            delete from gov.decision_records where event = 'admission.denied';
            update registry.seats set state = 'DRAFT', record_version = 1, configured_by = null, activated_by = null,
                pack_version_id = '%s'
            where name = 'seat_sourcing_poc';
            """
            % self.version_id,
        )

    def test_idempotent_start_instance(self) -> None:
        self._activate_seat()
        key = str(uuid.uuid4())
        r1 = self._start(idempotency_key=key)
        self.assertEqual(r1.status_code, 201, r1.text)
        id1 = r1.json()["instance_id"]
        r2 = self._start(idempotency_key=key)
        self.assertEqual(r2.status_code, 201, r2.text)
        self.assertEqual(r2.json()["instance_id"], id1)
        count = _pg.admin_sql(
            self.db, "select count(*) from work.instances where idempotency_key = '%s'" % key
        ).stdout.strip()
        self.assertEqual(count, "1")
        role = _pg.admin_sql(
            self.db,
            f"select role from work.participants where instance_id = '{id1}' and person_id = 'faisal'",
        ).stdout.strip()
        self.assertEqual(role, "requester")

    def test_non_requester_start_forbidden(self) -> None:
        self._activate_seat()
        r = self._start(person="khalid")
        self.assertEqual(r.status_code, 403, r.text)
        self.assertEqual(r.json()["code"], "not_permitted")

    def test_paused_seat_seat_not_active(self) -> None:
        self._activate_seat()
        _pg.admin_sql(self.db, f"update registry.seats set state = 'PAUSED' where name = '{SEAT}' and state = 'ACTIVE'")
        r = self._start()
        self.assertEqual(r.status_code, 403, r.text)
        self.assertEqual(r.json()["code"], "seat_not_active")

    def test_budget_exhausted_commits_dr_only(self) -> None:
        self._activate_seat()
        _pg.admin_sql(
            self.db,
            f"""
            insert into gov.budget_ledger (org_id, seat, day, limit_usd, reserved_usd, settled_usd)
            values ('org_demo', '{SEAT}', current_date, 20, 20, 0);
            """,
        )
        r = self._start()
        self.assertEqual(r.status_code, 403, r.text)
        self.assertEqual(r.json()["code"], "budget_exhausted")
        self.assertIn("decision_id", r.json())
        inst_count = _pg.admin_sql(self.db, "select count(*) from work.instances").stdout.strip()
        self.assertEqual(inst_count, "0")
        dr = _pg.admin_sql(
            self.db,
            f"select value from gov.decision_records where id = '{r.json()['decision_id']}'",
        ).stdout.strip()
        self.assertEqual(dr, "budget_exhausted")

    def test_post_turn_while_live_attempt_stores_turn_only(self) -> None:
        self._activate_seat()
        start = self._start()
        self.assertEqual(start.status_code, 201, start.text)
        inst_id = start.json()["instance_id"]
        r = self.client.post(
            f"/api/instances/{inst_id}/turns",
            headers=self.login("faisal"),
            json={"text": "Follow-up while agent runs", "client_turn_id": "ct-live-1"},
        )
        self.assertEqual(r.status_code, 202, r.text)
        body = r.json()
        self.assertIsNone(body["attempt_id"])
        self.assertEqual(body["turn"]["blocks"][0]["text"], "Follow-up while agent runs")

    def test_turn_filter_by_audience_roles(self) -> None:
        self._activate_seat()
        start = self._start()
        inst_id = start.json()["instance_id"]
        _pg.admin_sql(
            self.db,
            f"""
            insert into work.turns (id, instance_id, seq, author_kind, author_id, audience_roles, blocks, client_turn_id)
            values ('turn_buyer_only', '{inst_id}', 99, 'system', 'kernel', array['buyer']::text[],
                    '{{"kind":"text","text":"hidden"}}'::jsonb, 'fixture-buyer');
            """,
        )
        snap = self.client.get(f"/api/instances/{inst_id}", headers=self.login("faisal")).json()
        seqs = [t["seq"] for t in snap["turns"]]
        self.assertNotIn(99, seqs)

    def test_list_digital_workers_matches_seat_audience(self) -> None:
        self._activate_seat()
        faisal = self.client.get("/api/workspace/digital-workers", headers=self.login("faisal")).json()["items"]
        khalid = self.client.get("/api/workspace/digital-workers", headers=self.login("khalid")).json()["items"]
        match = next((d for d in faisal if d["seat"] == SEAT), None)
        self.assertIsNotNone(match)
        self.assertTrue(any(w["name"] == WORKFLOW for w in match["workflows"]))
        self.assertFalse(any(d["seat"] == SEAT for d in khalid))

    def test_seat_state_changed_reaches_may_start_audience(self) -> None:
        self._activate_seat()
        raw = _pg.admin_sql(
            self.db,
            "select stream from evidence.outbox where event_type = 'seat.state_changed'",
        ).stdout.strip()
        streams = set(raw.splitlines()) if raw else set()
        self.assertIn(ids.stream_user("faisal"), streams)

    def test_skill_from_workflow_initial_template(self) -> None:
        alt = self.packs / "procurement_alt"
        shutil.copytree(self.packs / "procurement_demo", alt)
        pack_yaml = alt / "pack.yaml"
        pack_yaml.write_text(
            pack_yaml.read_text().replace("name: procurement_demo", "name: procurement_alt", 1)
        )
        wf = alt / "workflows" / "quick_quote.yaml"
        text = wf.read_text()
        text = text.replace("skill: request_intake", "skill: alt_intake", 1)
        wf.write_text(text)
        shutil.copytree(
            alt / "skills" / "request_intake",
            alt / "skills" / "alt_intake",
        )
        (alt / "skills" / "alt_intake" / "skill.yaml").write_text(
            (alt / "skills" / "alt_intake" / "skill.yaml")
            .read_text()
            .replace("name: request_intake", "name: alt_intake")
        )
        seat_yaml = alt / "seats" / "seat_sourcing_poc.yaml"
        seat_yaml.write_text(seat_yaml.read_text().replace("request_intake", "alt_intake"))
        settings = Settings.from_env(
            database_url=_pg.kernel_url(self.db),
            packs_dir=self.packs,
            session_secret="test-secret-" + "x" * 40,
        )
        client = TestClient(create_app(settings))
        with client:
            vid = client.post(
                "/api/console/packs/procurement_alt/sync",
                headers=self._auth("platform_admin"),
                json={"source": "test"},
            ).json()["pack_version_id"]
            client.post(
                f"/api/console/pack-versions/{vid}/publish-requests",
                headers=self._auth("platform_admin"),
            )
            items = client.get("/api/console/publish-requests", headers=self._auth("risk")).json()["items"]
            req = next(i for i in items if i["pack_version_id"] == vid)
            client.post(
                f"/api/console/publish-requests/{req['id']}/approve",
                headers=self._auth("risk"),
                json={"part": "policies"},
            )
            client.post(
                f"/api/console/publish-requests/{req['id']}/approve",
                headers=self._auth("head_of_procurement"),
                json={"part": "seats_and_workflows"},
            )
            async def _seats() -> None:
                async with await psycopg.AsyncConnection.connect(_pg.kernel_url(self.db)) as conn:
                    async with conn.transaction():
                        await insert_seats_for_published_pack(
                            conn, org=ORG, org_id=ORG.organization.id, pack_version_id=vid
                        )

            asyncio.run(_seats())
            _pg.admin_sql(
                self.db,
                f"update registry.seats set state = 'ACTIVE', pack_version_id = '{vid}'"
                f" where name = '{SEAT}' and version = 1;",
            )
            r = client.post(
                "/api/instances",
                headers={**self.login("faisal"), "Idempotency-Key": str(uuid.uuid4())},
                json={"seat": SEAT, "workflow": WORKFLOW, "first_message": "Alt skill path"},
            )
            self.assertEqual(r.status_code, 201, r.text)
            inst_id = r.json()["instance_id"]
            skill = _pg.admin_sql(
                self.db, f"select skill from work.tasks where instance_id = '{inst_id}'"
            ).stdout.strip()
            self.assertEqual(skill, "alt_intake")

    def test_start_budget_backstop_leaves_no_partial_rows(self) -> None:
        self._activate_seat()
        _pg.admin_sql(
            self.db,
            f"""
            insert into gov.budget_ledger (org_id, seat, day, limit_usd, reserved_usd, settled_usd)
            values ('org_demo', '{SEAT}', current_date, 20, 20, 0)
            on conflict (org_id, seat, day) do update
            set reserved_usd = 20, settled_usd = 0, limit_usd = 20;
            """,
        )
        with patch("aos.kernel.admission._budget_fits", new_callable=AsyncMock, return_value=True):
            r = self._start(message="Backstop start")
        self.assertEqual(r.status_code, 403, r.text)
        self.assertEqual(r.json()["code"], "budget_exhausted")
        self.assertIn("decision_id", r.json())
        for table in ("work.instances", "work.tasks", "work.turns", "work.attempts"):
            count = _pg.admin_sql(self.db, f"select count(*) from {table}").stdout.strip()
            self.assertEqual(count, "0", table)
        dr = _pg.admin_sql(
            self.db,
            f"select value from gov.decision_records where id = '{r.json()['decision_id']}'",
        ).stdout.strip()
        self.assertEqual(dr, "budget_exhausted")

    def test_budget_backstop_when_ledger_check_fails(self) -> None:
        self._activate_seat()
        start = self._start()
        self.assertEqual(start.status_code, 201, start.text)
        inst_id = start.json()["instance_id"]
        _pg.admin_sql(
            self.db,
            f"""
            update work.attempts set state = 'ENDED', outcome = 'submitted', ended_at = now()
            where task_id in (select id from work.tasks where instance_id = '{inst_id}');
            update work.tasks set state = 'WAITING_INPUT' where instance_id = '{inst_id}';
            insert into gov.budget_ledger (org_id, seat, day, limit_usd, reserved_usd, settled_usd)
            values ('org_demo', '{SEAT}', current_date, 20, 20, 0)
            on conflict (org_id, seat, day) do update
            set reserved_usd = 20, settled_usd = 0, limit_usd = 20;
            """,
        )
        with patch("aos.kernel.admission._budget_fits", new_callable=AsyncMock, return_value=True):
            r = self.client.post(
                f"/api/instances/{inst_id}/turns",
                headers=self.login("faisal"),
                json={"text": "Should refuse at ledger", "client_turn_id": "bt-backstop"},
            )
        self.assertEqual(r.status_code, 403, r.text)
        self.assertEqual(r.json()["code"], "budget_exhausted")
        self.assertIn("decision_id", r.json())
        turn_count = _pg.admin_sql(
            self.db,
            "select count(*) from work.turns where client_turn_id = 'bt-backstop'",
        ).stdout.strip()
        self.assertEqual(turn_count, "0")
        dr = _pg.admin_sql(
            self.db,
            f"select value from gov.decision_records where id = '{r.json()['decision_id']}'",
        ).stdout.strip()
        self.assertEqual(dr, "budget_exhausted")
        audit = self.client.get("/api/console/audit?limit=20", headers=self.login("risk")).json()["items"]
        self.assertTrue(any(a["action"] == "admission.denied" for a in audit))

    def test_unknown_workflow_is_404_without_decision_record(self) -> None:
        self._activate_seat()
        before = _pg.admin_sql(
            self.db, "select count(*) from gov.decision_records where event = 'admission.denied'"
        ).stdout.strip()
        r = self.client.post(
            "/api/instances",
            headers=self.login("faisal"),
            json={"seat": SEAT, "workflow": "not_a_real_workflow", "first_message": "Hi"},
        )
        self.assertEqual(r.status_code, 404, r.text)
        self.assertEqual(r.json()["code"], "not_found")
        after = _pg.admin_sql(
            self.db, "select count(*) from gov.decision_records where event = 'admission.denied'"
        ).stdout.strip()
        self.assertEqual(before, after)

    def test_start_idempotency_unique_race_returns_snapshot(self) -> None:
        self._activate_seat()
        key = str(uuid.uuid4())
        _pg.admin_sql(
            self.db,
            f"""
            insert into work.instances (
              id, org_id, workflow, pack_version_id, seat, seat_version, title, state,
              created_by, idempotency_key, correlation_id
            ) values (
              'QQ-race', 'org_demo', '{WORKFLOW}', '{self.version_id}', '{SEAT}', 1,
              'race', 'intake', 'faisal', '{key}', 'corr_race'
            );
            insert into work.participants (instance_id, role, person_id, bound_by)
            values ('QQ-race', 'requester', 'faisal', 'creation');
            """,
        )
        from aos.kernel import instances as inst_mod

        real_lookup = inst_mod._idempotent_instance_id
        calls = {"n": 0}

        async def lookup_once_miss(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                return None
            return await real_lookup(*args, **kwargs)

        with patch.object(inst_mod, "_idempotent_instance_id", side_effect=lookup_once_miss):
            r = self._start(idempotency_key=key)
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual(r.json()["instance_id"], "QQ-race")

    def test_start_refuses_when_pack_on_disk_drifts(self) -> None:
        self._activate_seat()
        instr = self.packs / "procurement_demo" / "skills" / "request_intake" / "instructions.md"
        original = instr.read_text()
        try:
            instr.write_text(original + "\n# drift\n")
            r = self._start()
            self.assertEqual(r.status_code, 409, r.text)
            self.assertEqual(r.json()["code"], "conflict")
            self.assertIn("Pack content changed", r.json()["title"])
        finally:
            instr.write_text(original)


if __name__ == "__main__":
    unittest.main()
