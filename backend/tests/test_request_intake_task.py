"""request_intake as a workflow Task with resume-on-input (M2-AG-01 part 2)."""

from __future__ import annotations

import asyncio
import json
import unittest
import uuid

from aos.worker.checkpointer import CheckpointerHandle
from aos.worker.runner import Worker
from aos.worker.runtime import FakeRuntime

from . import _pg
from .test_worker_api import WorkerHarness
from .worker_harness import make_http_client, mock_erp_hook


@unittest.skipUnless(_pg.available(), "no local Postgres")
class RequestIntakeTaskTests(WorkerHarness, unittest.IsolatedAsyncioTestCase):
    async def _run_task_fake_once(self, script: str = "request_intake.happy.yaml") -> str:
        _pg.require_runtime_extra()
        client = await make_http_client(self, invoke_hook=mock_erp_hook)
        handle = await CheckpointerHandle.open(_pg.worker_checkpoint_url(self.db))
        try:
            runtime = FakeRuntime(checkpointer=handle, script=script)
            worker = Worker("worker-test-1", client, runtime, ("assist", "task"))
            return await asyncio.wait_for(worker.run_once(), 120)
        finally:
            await handle.close()
            await client.aclose()

    async def test_intake_task_commands_carry_typed_schemas(self) -> None:
        await asyncio.to_thread(self._start_job)
        client = await make_http_client(self, invoke_hook=mock_erp_hook)
        attempt = await client.claim("worker-test-1", ["task"])
        assert attempt
        envelope = await client.assemble_context(attempt, reason="start")
        await client.aclose()
        names = {c["name"] for c in envelope.get("commands") or []}
        self.assertNotIn("read_artifact", names)
        save = next(c for c in envelope["commands"] if c["name"] == "save_draft")
        props = save["input_schema"].get("properties") or {}
        self.assertIn("content", props)
        content_props = (props.get("content") or {}).get("properties") or {}
        self.assertIn("delivery_date", content_props)
        ask = next(c for c in envelope["commands"] if c["name"] == "ask_question")
        qschema = ask["input_schema"]["properties"]["questions"]
        self.assertEqual(qschema.get("maxItems"), 3)

    def test_start_admits_intake_task_attempt(self) -> None:
        inst = self._start_job()
        row = _pg.admin_sql(
            self.db,
            f"""
            select t.kind, t.template, a.turn_id is not null
            from work.attempts a
            join work.tasks t on t.id = a.task_id
            where t.instance_id = '{inst}'
            order by a.admitted_at asc limit 1;
            """,
        ).stdout.strip()
        self.assertEqual(row, "task|request_intake|t")
        assist_attempts = _pg.admin_sql(
            self.db,
            f"select count(*) from work.attempts a join work.tasks t on t.id = a.task_id"
            f" where t.instance_id = '{inst}' and t.kind = 'assist';",
        ).stdout.strip()
        self.assertEqual(assist_attempts, "0")

    async def test_happy_two_attempts_brief_versions(self) -> None:
        inst = await asyncio.to_thread(self._start_job)
        outcome1 = await self._run_task_fake_once()
        self.assertEqual(outcome1, "waiting", outcome1)
        task_state = _pg.admin_sql(
            self.db,
            "select state from work.tasks where kind = 'task' and template = 'request_intake'"
            " order by created_at desc limit 1;",
        ).stdout.strip()
        self.assertEqual(task_state, "WAITING_INPUT")

        def post_answer() -> dict:
            resp = self.client.post(
                f"/api/instances/{inst}/turns",
                headers={**self._auth("faisal"), "Idempotency-Key": str(uuid.uuid4())},
                json={"text": "North warehouse, 2026-11-01, budget 15000", "client_turn_id": "ri-answer"},
            )
            self.assertEqual(resp.status_code, 202, resp.text)
            return resp.json()

        turn_body = await asyncio.to_thread(post_answer)
        self.assertIsNotNone(turn_body.get("attempt_id"))
        outcome2 = await self._run_task_fake_once()
        self.assertEqual(outcome2, "submitted", outcome2)
        versions = _pg.admin_sql(
            self.db,
            "select count(*) from work.artifact_versions av"
            " join work.artifacts a on a.id = av.artifact_id"
            f" where a.instance_id = '{inst}' and a.artifact_type = 'brief';",
        ).stdout.strip()
        self.assertGreaterEqual(int(versions), 2)

    def test_buyer_turn_uses_sourcing_assist(self) -> None:
        inst = self._start_job()
        tr = self.client.post(
            f"/api/instances/{inst}/turns",
            headers={**self._auth("noura"), "Idempotency-Key": str(uuid.uuid4())},
            json={"text": "Hello from buyer", "client_turn_id": "buyer-intake"},
        )
        self.assertEqual(tr.status_code, 403, tr.text)

    async def test_buyer_participant_runs_sourcing_assist(self) -> None:
        inst = await asyncio.to_thread(self._start_job)
        _pg.admin_sql(
            self.db,
            f"insert into work.participants (instance_id, role, person_id, bound_by)"
            f" values ('{inst}', 'buyer', 'noura', 'claim') on conflict do nothing;",
        )
        tr = self.client.post(
            f"/api/instances/{inst}/turns",
            headers={**self._auth("noura"), "Idempotency-Key": str(uuid.uuid4())},
            json={"text": "Where are we?", "client_turn_id": "buyer-intake-2"},
        )
        self.assertEqual(tr.status_code, 202, tr.text)
        skill = _pg.admin_sql(
            self.db,
            f"""
            select t.skill from work.attempts a
            join work.tasks t on t.id = a.task_id
            where a.id = '{tr.json()["attempt_id"]}';
            """,
        ).stdout.strip()
        self.assertEqual(skill, "sourcing_assist")

    async def test_revise_voids_brief_decision_until_task_completes(self) -> None:
        import psycopg
        from aos.kernel import decisions as dec_ops, ids
        from aos.kernel.org import load_org
        from aos.kernel.settings import REPO

        from .test_decisions import _brief_v, _insert_brief, _insert_instance, _insert_task_completed

        await asyncio.to_thread(self._activate_seat)
        inst = "QQ-INT-REV"
        async with await psycopg.AsyncConnection.connect(_pg.kernel_url(self.db)) as conn:
            async with conn.transaction():
                await _insert_instance(conn, instance_id=inst, pack_version_id=self.version_id)
                await _insert_task_completed(conn, inst, "request_intake")
                await conn.execute(
                    """
                    update work.tasks set contract = %s
                    where instance_id = %s and template = 'request_intake' and kind = 'task'
                    """,
                    (
                        json.dumps(
                            {
                                "on_behalf_of": {"role": "requester"},
                                "budget": {
                                    "cost_usd": 0.5,
                                    "tokens": 20000,
                                    "seconds": 120,
                                    "steps": 4,
                                    "actions": 4,
                                },
                            }
                        ),
                        inst,
                    ),
                )
                await _insert_brief(conn, inst, [_brief_v(2)])
            await dec_ops.open_ready_decisions(
                conn, inst, org=load_org(REPO / "seed" / "org.yaml"), packs_dir=self.packs
            )
        _pg.admin_sql(
            self.db,
            f"insert into work.participants (instance_id, role, person_id, bound_by)"
            f" values ('{inst}', 'requester', 'faisal', 'creation') on conflict do nothing;",
        )
        open_before = _pg.admin_sql(
            self.db,
            f"select count(*) from work.pending_items where instance_id = '{inst}'"
            f" and event = 'decision.brief_confirmed' and status = 'open';",
        ).stdout.strip()
        self.assertEqual(open_before, "1")

        tr = self.client.post(
            f"/api/instances/{inst}/turns",
            headers={**self._auth("faisal"), "Idempotency-Key": str(uuid.uuid4())},
            json={"text": "Change the quantity to 5", "client_turn_id": "revise-msg"},
        )
        self.assertEqual(tr.status_code, 202, tr.text)
        open_during = _pg.admin_sql(
            self.db,
            f"select count(*) from work.pending_items where instance_id = '{inst}'"
            f" and event = 'decision.brief_confirmed' and status = 'open';",
        ).stdout.strip()
        self.assertEqual(open_during, "0")
        superseded = _pg.admin_sql(
            self.db,
            "select count(*) from work.tasks where instance_id = '%s' and template = 'request_intake'"
            " and superseded_by is not null;" % inst,
        ).stdout.strip()
        self.assertEqual(superseded, "1")

    async def test_latest_exception_then_retry_opens_decision(self) -> None:
        import psycopg
        from aos.kernel import decisions as dec_ops, ids

        from .test_decisions import _brief_v, _insert_brief, _insert_instance, _insert_task_completed

        inst = "QQ-INT-LATEST"
        async with await psycopg.AsyncConnection.connect(_pg.kernel_url(self.db)) as conn:
            async with conn.transaction():
                await _insert_instance(conn, instance_id=inst, pack_version_id=self.version_id)
                old_id = ids.new_task_id()
                await conn.execute(
                    """
                    insert into work.tasks (
                      id, instance_id, kind, template, skill, work_type, state, contract, contract_hash, max_attempts
                    ) values (%s, %s, 'task', 'request_intake', 'request_intake', 'analysis', 'EXCEPTION',
                              '{}', 'h1', 3)
                    """,
                    (old_id, inst),
                )
                await conn.execute(
                    "update work.tasks set created_at = created_at - interval '1 hour' where id = %s",
                    (old_id,),
                )
                await _insert_task_completed(conn, inst, "request_intake")
                await _insert_brief(conn, inst, [_brief_v(2)])
            opened = await dec_ops.open_ready_decisions(
                conn, inst, org=__import__("aos.kernel.org", fromlist=["load_org"]).load_org(
                    __import__("aos.kernel.settings", fromlist=["REPO"]).REPO / "seed" / "org.yaml"
                ),
                packs_dir=self.packs,
            )
        self.assertEqual(len(opened), 1)

    def test_clearance_from_org_role_name(self) -> None:
        import yaml
        from aos.kernel import contracts
        from aos.kernel.org import OrgModel

        from .test_task_contracts import PACKS_DIR, _defs, _limits, _seat

        alt_org = OrgModel.model_validate(
            yaml.safe_load(
                """
organization: {id: org_alt, name: Alt, data_residency: sandbox}
role_clearances: {requester_role: shareable, buyer_role: restricted}
departments:
  d:
    name: D
    head: p1
    teams: {t: {name: T, owner: p1}}
people:
  p1: {name: P, team: d/t, roles: [requester_role]}
"""
            )
        )
        c = contracts.build_task_contract(
            packs_dir=PACKS_DIR,
            pack_name="procurement_demo",
            pack_version=1,
            pack_digest="test",
            defs=_defs(),
            org_id="org_alt",
            instance_id="QQ-CL",
            task_id="task_cl",
            seat_name="seat_sourcing_poc",
            seat_version=1,
            seat_doc=_seat(),
            workflow_name="quick_quote",
            template={
                "template": "request_intake",
                "skill": "request_intake",
                "work_type": "analysis",
                "on_behalf_of": "requester",
            },
            participant_role="requester",
            person_id="p1",
            seat_limits=_limits(),
            org=alt_org,
        )
        self.assertEqual(c["permission_scope"]["classification_ceiling"], "shareable")
