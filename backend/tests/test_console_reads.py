"""M2-BE-06: Console reads and user event stream."""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path

import psycopg
from fastapi.testclient import TestClient

from aos.api import create_app
from aos.kernel import ids, workflow
from aos.kernel.org import load_org, seed_sql
from aos.kernel.registry_store import sync_pack
from aos.kernel.seats import insert_seats_for_published_pack
from aos.kernel.settings import REPO, Settings

from . import _pg
from .test_instance_stream import _parse_sse_block

ORG = load_org(REPO / "seed" / "org.yaml")
ORG_ID = ORG.organization.id
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


@unittest.skipUnless(_pg.available(), "needs Postgres")
class ConsoleReadsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.db = _pg.create_migrated()
        cls.packs_dir = Path(tempfile.mkdtemp(prefix="aos-console-"))
        shutil.copytree(REPO / "packs" / "procurement_demo", cls.packs_dir / "procurement_demo")
        cls.settings = Settings.from_env(
            database_url=_pg.kernel_url(cls.db),
            packs_dir=cls.packs_dir,
            session_secret="test-secret-" + "x" * 40,
            sse_heartbeat_seconds=0.25,
        )
        cls.client = TestClient(create_app(cls.settings))
        cls.client.__enter__()
        cls.url = _pg.kernel_url(cls.db)
        asyncio.run(cls._seed())

    @classmethod
    async def _seed(cls) -> None:
        conn = await psycopg.AsyncConnection.connect(cls.url)
        await conn.execute(seed_sql(ORG))
        cls.pack_version_id = await _sync_published(conn, cls.packs_dir)
        await insert_seats_for_published_pack(
            conn, org=ORG, org_id=ORG_ID, pack_version_id=cls.pack_version_id
        )
        await conn.commit()
        await conn.close()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client.__exit__(None, None, None)
        _pg.drop(cls.db)
        shutil.rmtree(cls.packs_dir, ignore_errors=True)

    def auth(self, person: str) -> dict[str, str]:
        token = self.client.post("/api/auth/session", json={"person_id": person}).json()["token"]
        return {"Authorization": f"Bearer {token}"}

    def setUp(self) -> None:
        _pg.admin_sql(
            self.db,
            """
            delete from evidence.outbox;
            delete from evidence.execution_events;
            delete from work.turns;
            delete from work.attempts;
            delete from work.tasks;
            delete from work.pending_items;
            delete from work.instance_transitions;
            delete from work.regions;
            delete from work.timers;
            delete from work.participants;
            delete from work.instances;
            """,
        )

    def test_list_workflows_running_count(self) -> None:
        async def _run() -> None:
            conn = await psycopg.AsyncConnection.connect(self.url)
            for i in (1, 2):
                await conn.execute(
                    """
                    insert into work.instances (
                      id, org_id, workflow, pack_version_id, seat, seat_version, title, state, version,
                      status, created_by, correlation_id
                    ) values (%s, %s, %s, %s, %s, 1, %s, 'intake', 1, 'running', 'faisal', %s)
                    """,
                    (f"QQ-C{i}", ORG_ID, WORKFLOW, self.pack_version_id, SEAT, f"Job {i}", f"c{i}"),
                )
            await conn.commit()
            await conn.close()

        asyncio.run(_run())
        r = self.client.get("/api/console/workflows", headers=self.auth("risk"))
        self.assertEqual(r.status_code, 200, r.text)
        qq = next(x for x in r.json()["items"] if x["name"] == WORKFLOW)
        self.assertGreaterEqual(qq["running"], 2)

    def test_get_workflow_graph_needs_approval(self) -> None:
        r = self.client.get(
            f"/api/console/workflows/{WORKFLOW}",
            headers=self.auth("head_of_procurement"),
            params={"version": 1},
        )
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["name"], WORKFLOW)
        self.assertEqual(body["version"], 1)
        self.assertEqual(body["initial"], "intake")
        by_template = {}
        for st in body["states"]:
            for t in st.get("tasks") or []:
                by_template[t["template"]] = t.get("needs_approval")
        self.assertFalse(by_template["rfq_draft"])
        self.assertTrue(by_template["rfq_send"])
        self.assertTrue(by_template["po_create"])
        tr = next(t for t in body["transitions"] if t["from"] == "awaiting_quotes" and t["to"] == "comparison")
        self.assertIsInstance(tr["on"], list)
        self.assertEqual(len(tr["on"]), 2)

    def test_needs_approval_ignores_renamed_gate_rule_id(self) -> None:
        alt_packs = Path(tempfile.mkdtemp(prefix="aos-console-gate-"))
        shutil.copytree(self.packs_dir / "procurement_demo", alt_packs / "procurement_demo")
        gates = alt_packs / "procurement_demo" / "policies" / "quick_quote_gates.yaml"
        gates.write_text(
            gates.read_text().replace("id: rfq_send", "id: send_rfq_gate", 1)
        )
        pack_yaml = alt_packs / "procurement_demo" / "pack.yaml"
        pack_yaml.write_text(
            re.sub(r"version: (\d+)", lambda m: f"version: {int(m.group(1)) + 1}", pack_yaml.read_text(), count=1)
        )

        async def _run() -> str:
            conn = await psycopg.AsyncConnection.connect(self.url)
            pvid = await _sync_published(conn, alt_packs)
            await conn.commit()
            await conn.close()
            return pvid

        asyncio.run(_run())
        r = self.client.get(
            f"/api/console/workflows/{WORKFLOW}",
            headers=self.auth("risk"),
        )
        self.assertEqual(r.status_code, 200, r.text)
        by_template = {}
        for st in r.json()["states"]:
            for t in st.get("tasks") or []:
                by_template[t["template"]] = t.get("needs_approval")
        self.assertTrue(by_template["rfq_send"])
        shutil.rmtree(alt_packs, ignore_errors=True)

    def test_list_instances_filters_and_summary(self) -> None:
        async def _run() -> None:
            from datetime import timedelta

            from aos.kernel import clock as kclock

            conn = await psycopg.AsyncConnection.connect(self.url)
            now = kclock.now()
            over_entered = now - timedelta(days=10)
            base = (ORG_ID, WORKFLOW, self.pack_version_id, SEAT)
            for iid, title, state, status, entered in (
                ("QQ-P1", "Pending person", "intake", "running", now),
                ("QQ-T1", "Timer only", "awaiting_quotes", "running", now),
                ("QQ-K1", "Task running", "rfq_drafting", "running", now),
                ("QQ-O1", "Over target", "awaiting_quotes", "running", over_entered),
                ("QQ-C1", "Closed job", "closed", "closed", now),
            ):
                await conn.execute(
                    """
                    insert into work.instances (
                      id, org_id, workflow, pack_version_id, seat, seat_version, title, state, version,
                      status, state_entered_at, created_by, correlation_id
                    ) values (%s, %s, %s, %s, %s, 1, %s, %s, 1, %s, %s, 'faisal', %s)
                    """,
                    (iid, *base, title, state, status, entered, iid),
                )
            await conn.execute(
                "update work.instances set closed_at = %s where id = 'QQ-C1'",
                (now,),
            )
            await conn.execute(
                "insert into work.pending_items (id, instance_id, kind, event, title, for_role, for_person_id)"
                " values ('pend_1', 'QQ-P1', 'decision', 'decision.brief_confirmed', 'Confirm brief', 'requester', 'faisal')"
            )
            await conn.execute(
                "insert into work.timers (id, instance_id, name, emits, fires_at, status)"
                " values ('tmr_1', 'QQ-T1', 'quote_deadline', 'quotes_closed', %s, 'scheduled')",
                (now + timedelta(hours=1),),
            )
            tid = ids.new_task_id()
            await conn.execute(
                """
                insert into work.tasks (
                  id, instance_id, kind, template, skill, work_type, state, contract, contract_hash, max_attempts
                ) values (%s, 'QQ-K1', 'task', 'rfq_draft', 'rfq_authoring', 'document_draft', 'RUNNING', '{}', 'h', 3)
                """,
                (tid,),
            )
            await conn.commit()
            await conn.close()

        asyncio.run(_run())
        all_r = self.client.get("/api/console/instances", headers=self.auth("platform_admin"))
        self.assertEqual(all_r.status_code, 200)
        summary = all_r.json()["summary"]
        self.assertEqual(summary["running"], 4)
        self.assertGreaterEqual(summary["waiting_on_person"], 1)
        self.assertGreaterEqual(summary["over_target"], 1)
        self.assertGreaterEqual(summary["closed_this_week"], 1)

        person_r = self.client.get(
            "/api/console/instances",
            headers=self.auth("platform_admin"),
            params={"waiting_on": "person"},
        )
        ids_person = {x["instance_id"] for x in person_r.json()["items"]}
        self.assertIn("QQ-P1", ids_person)

        timer_r = self.client.get(
            "/api/console/instances",
            params={"waiting_on": "timer"},
            headers=self.auth("platform_admin"),
        )
        self.assertIn("QQ-T1", {x["instance_id"] for x in timer_r.json()["items"]})

        task_r = self.client.get(
            "/api/console/instances",
            params={"waiting_on": "task"},
            headers=self.auth("platform_admin"),
        )
        self.assertIn("QQ-K1", {x["instance_id"] for x in task_r.json()["items"]})

        q_r = self.client.get(
            "/api/console/instances",
            params={"q": "timer only"},
            headers=self.auth("platform_admin"),
        )
        self.assertEqual(len(q_r.json()["items"]), 1)
        self.assertEqual(q_r.json()["items"][0]["instance_id"], "QQ-T1")

    def test_timeline_stages_and_order(self) -> None:
        inst = "QQ-TL1"

        async def _run() -> None:
            conn = await psycopg.AsyncConnection.connect(self.url)
            await conn.execute(
                """
                insert into work.instances (
                  id, org_id, workflow, pack_version_id, seat, seat_version, title, state, version,
                  attributes, created_by, correlation_id
                ) values (%s, %s, %s, %s, %s, 1, 'Timeline job', 'intake', 1, '{}', 'faisal', 'tl')
                """,
                (inst, ORG_ID, WORKFLOW, self.pack_version_id, SEAT),
            )
            await conn.execute(
                "insert into work.participants (instance_id, role, person_id, bound_by)"
                " values (%s, 'requester', 'faisal', 'creation'), (%s, 'buyer', 'noura', 'claim')",
                (inst, inst),
            )
            await conn.commit()
            await workflow.apply_event(
                conn,
                inst,
                "decision.brief_confirmed",
                by_role="requester",
                packs_dir=self.packs_dir,
                org=ORG,
            )
            await conn.execute(
                """
                insert into work.regions (
                  instance_id, name, state, started_on, join_at, join_guard, started_with
                ) values (%s, 'discovery', 'done', 'event.intent_identified', 'shortlisting', 'same(brief_version)', %s)
                on conflict (instance_id, name) do update set state = 'done'
                """,
                (inst, json.dumps({"brief_version": 1})),
            )
            await conn.execute(
                "update work.instances set attributes = attributes || %s::jsonb where id = %s",
                (json.dumps({"shortlist_count": 3, "brief_version": 1}), inst),
            )
            await workflow.apply_event(
                conn,
                inst,
                "decision.shortlist_confirmed",
                by_role="buyer",
                packs_dir=self.packs_dir,
                org=ORG,
            )
            await conn.execute(
                """
                insert into gov.decision_records (
                  id, org_id, subject_kind, subject_id, event, value, actor, actor_role, at
                ) values
                  ('dr_tl_brief', %s, 'instance', %s, 'decision.brief_confirmed', 'confirmed', 'faisal', 'requester', now()),
                  ('dr_tl_short', %s, 'instance', %s, 'decision.shortlist_confirmed', 'confirmed', 'noura', 'buyer', now())
                """,
                (ORG_ID, inst, ORG_ID, inst),
            )
            await conn.commit()
            await conn.close()

        asyncio.run(_run())
        r = self.client.get(f"/api/console/instances/{inst}/timeline", headers=self.auth("risk"))
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["instance_id"], inst)
        states = [s["state"] for s in body["stages"]]
        self.assertEqual(states[:3], ["intake", "shortlisting", "rfq_drafting"])
        for st in body["stages"]:
            self.assertGreaterEqual(st["duration_s"], 0)
        kinds = [e["kind"] for e in body["entries"]]
        self.assertIn("transition", kinds)
        self.assertIn("decision", kinds)
        ats = [e["at"] for e in body["entries"]]
        self.assertEqual(ats, sorted(ats))

    def test_workspace_person_denied_console(self) -> None:
        r = self.client.get("/api/console/workflows", headers=self.auth("faisal"))
        self.assertEqual(r.status_code, 403, r.text)

    def test_user_stream_delivers_and_resumes(self) -> None:
        inst = "QQ-EV1"

        async def _run() -> None:
            from aos.kernel.outbox import OutboxRow, append_outbox_many
            from aos.sse import user_event_stream

            conn = await psycopg.AsyncConnection.connect(self.url)
            await conn.execute(
                """
                insert into work.instances (
                  id, org_id, workflow, pack_version_id, seat, seat_version, title, state, version,
                  status, created_by, correlation_id
                ) values (%s, %s, %s, %s, %s, 1, 'Stream', 'intake', 1, 'running', 'faisal', 'ev')
                """,
                (inst, ORG_ID, WORKFLOW, self.pack_version_id, SEAT),
            )
            seqs = await append_outbox_many(
                conn,
                [
                    OutboxRow(
                        stream=ids.stream_user("faisal"),
                        event_type="instance.created",
                        instance_id=inst,
                        audience={"person_id": "faisal"},
                        data={"instance_id": inst, "title": "Stream", "workflow": WORKFLOW},
                    ),
                    OutboxRow(
                        stream=ids.stream_user("noura"),
                        event_type="pending.created",
                        instance_id=inst,
                        audience={"person_id": "noura"},
                        data={"instance_id": inst, "pending_id": "pend_x"},
                    ),
                ],
            )
            await conn.commit()
            await conn.close()

            faisal_stream = ids.stream_user("faisal")
            cursor_after_first = ids.ui_event_cursor(faisal_stream, seqs[faisal_stream])
            hub = self.client.app.state.hub
            pool = self.client.app.state.kernel.pool

            async def _collect(cursor: str | None, limit: int) -> list[dict]:
                blocks: list[dict] = []
                async for chunk in user_event_stream(
                    hub,
                    pool,
                    org_id=ORG_ID,
                    person_id="faisal",
                    cursor=cursor,
                ):
                    blocks.append(_parse_sse_block(chunk))
                    if len(blocks) >= limit:
                        break
                return blocks

            zero_cursor = ids.ui_event_cursor(faisal_stream, 0)
            first = await _collect(zero_cursor, 4)
            data_types = [b["data"]["type"] for b in first if b.get("data")]
            self.assertIn("instance.created", data_types)
            self.assertNotIn("pending.created", data_types)

            second = await _collect(cursor_after_first, 3)
            resumed_types = [b["data"]["type"] for b in second if b.get("data")]
            self.assertNotIn("instance.created", resumed_types)

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
