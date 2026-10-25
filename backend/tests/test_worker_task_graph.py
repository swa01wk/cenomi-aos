"""Task graph, FakeRuntime script pick, budgets (M2-AG-01 part 1)."""

from __future__ import annotations

import asyncio
import json
import unittest
from aos.kernel import contracts, ids
from aos.kernel.org import load_org
from aos.registry.loader import load_pack
from aos.worker.checkpointer import CheckpointerHandle, langgraph_thread_id
from aos.worker.fake_chat import chat_model_from_script
from aos.worker.errors import Fenced
from aos.worker.graphs.state import TaskGraphState
from aos.worker.protocol import AttemptContext
from aos.worker.runner import Worker
from aos.worker.runtime import FakeRuntime, _fake_script_name
from aos.worker.scripts_loader import load_fake_script

from pathlib import Path

from . import _pg
from .test_worker_api import WorkerHarness
from .worker_harness import make_http_client, mock_erp_hook

ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / "packs" / "procurement_demo"
ORG = load_org(ROOT / "seed" / "org.yaml")


def _pack_defs():
    loaded = load_pack(PACK)
    return {k: {n: o.model_dump(by_alias=True) for n, o in v.items()} for k, v in loaded.objects.items()}


def _patch_latest_task_budget(db: str, *, steps: int | None = None) -> None:
    if steps is None:
        return
    sql = (
        f"update work.tasks set contract = jsonb_set(contract, '{{budget,steps}}', '{int(steps)}'::jsonb, true) "
        "where id = (select t.id from work.tasks t where t.kind = 'task' order by t.created_at desc limit 1);"
    )
    _pg.admin_sql(db, sql)


@unittest.skipUnless(_pg.available(), "no local Postgres")
class TaskGraphWorkerTests(WorkerHarness, unittest.IsolatedAsyncioTestCase):
    def _task_contract(self, inst: str, task_id: str) -> dict:
        defs = _pack_defs()
        seat = defs["Seat"]["seat_sourcing_poc"]
        limits = seat["spec"]["limits"]
        digest = _pg.admin_sql(
            self.db,
            "select digest from registry.pack_versions where pack_name = 'procurement_demo' order by version desc limit 1;",
        ).stdout.strip()
        return contracts.build_task_contract(
            packs_dir=self.packs,
            pack_name="procurement_demo",
            pack_version=1,
            pack_digest=digest or "test",
            defs=defs,
            org_id="org_demo",
            instance_id=inst,
            task_id=task_id,
            seat_name="seat_sourcing_poc",
            seat_version=1,
            seat_doc=seat,
            workflow_name="quick_quote",
            template={
                "template": "request_intake",
                "skill": "request_intake",
                "work_type": "analysis",
                "verifier": "brief_schema",
                "on_behalf_of": "requester",
            },
            participant_role="requester",
            person_id="faisal",
            seat_limits=limits,
            org=ORG,
        )

    def _insert_task_row(self, inst: str) -> tuple[str, dict]:
        task_id = ids.new_task_id()
        contract = self._task_contract(inst, task_id)
        contract["kind"] = "task"
        contract["contract_hash"] = contracts.contract_hash(contract)
        attempt_id = ids.new_attempt_id()
        contract_sql = json.dumps(contract).replace("'", "''")
        _pg.admin_sql(
            self.db,
            f"""
            insert into work.tasks (
              id, instance_id, kind, template, skill, work_type, verifier, state, contract, contract_hash,
              max_attempts, fencing_token, attempts_used
            ) values (
              '{task_id}', '{inst}', 'task', 'request_intake', 'request_intake', 'analysis', 'brief_schema',
              'RUNNING', '{contract_sql}'::jsonb, '{contract["contract_hash"]}', 4, 1, 1
            );
            insert into work.attempts (id, task_id, n, fencing_token, state, reserved_usd)
            values ('{attempt_id}', '{task_id}', 1, 2, 'ADMITTED', 1.0);
            update work.tasks set fencing_token = 2 where id = '{task_id}';
            """,
        )
        return task_id, contract

    async def _run_task_fake(self, script: str, *, budget_steps: int | None = None) -> str:
        inst = await asyncio.to_thread(self._start_job)
        self._insert_task_row(inst)
        if budget_steps is not None:
            _patch_latest_task_budget(self.db, steps=budget_steps)
        client = await make_http_client(self, invoke_hook=mock_erp_hook)
        _pg.require_runtime_extra()
        handle = await CheckpointerHandle.open(_pg.worker_checkpoint_url(self.db))
        try:
            runtime = FakeRuntime(checkpointer=handle, script=script)
            worker = Worker("worker-test-1", client, runtime, ("task",))
            return await asyncio.wait_for(worker.run_once(), 120)
        finally:
            await handle.close()
            await client.aclose()

    async def test_happy_saves_draft_and_submits(self) -> None:
        outcome = await self._run_task_fake("request_intake.task_test.yaml")
        self.assertEqual(outcome, "submitted", outcome)
        versions = _pg.admin_sql(
            self.db,
            "select count(*) from work.artifact_versions av"
            " join work.attempts a on a.id = av.produced_by"
            " join work.tasks t on t.id = a.task_id where t.kind = 'task';",
        ).stdout.strip()
        self.assertGreater(int(versions or 0), 0)

    async def test_ask_question_ends_waiting(self) -> None:
        outcome = await self._run_task_fake("request_intake.ask_test.yaml")
        self.assertEqual(outcome, "waiting", outcome)
        state = _pg.admin_sql(
            self.db,
            "select state from work.tasks where kind = 'task' order by updated_at desc limit 1;",
        ).stdout.strip()
        self.assertEqual(state, "WAITING_INPUT")

    async def test_loop_budget_exhausted_no_submit(self) -> None:
        outcome = await self._run_task_fake("request_intake.loop.yaml", budget_steps=8)
        self.assertEqual(outcome, "failed:budget_exhausted", outcome)
        submitted = _pg.admin_sql(
            self.db,
            "select count(*) from work.attempts where outcome = 'submitted' and task_id in (select id from work.tasks where kind = 'task');",
        ).stdout.strip()
        self.assertEqual(submitted, "0")

    async def test_fenced_stops_before_next_node(self) -> None:
        inst = await asyncio.to_thread(self._start_job)
        self._insert_task_row(inst)
        client = await make_http_client(self, invoke_hook=mock_erp_hook)
        _pg.require_runtime_extra()
        handle = await CheckpointerHandle.open(_pg.worker_checkpoint_url(self.db))
        try:
            attempt = await client.claim("worker-test-1", ["task"])
            assert attempt
            resolved = await handle.resolve(attempt)
            fenced = asyncio.Event()
            ctx = AttemptContext(attempt, client, fenced)
            script = load_fake_script("request_intake.loop.yaml")
            model = chat_model_from_script(script)
            graph = handle.task_graph(interrupt_after=["load"])
            config = {
                "configurable": {
                    "thread_id": resolved.thread_id,
                    "ctx": ctx,
                    "chat_model": model,
                    "attempt": attempt,
                    "adapter": "fake",
                }
            }
            initial: TaskGraphState = {"worker_notes": [], "actions_this_reply": [], "draft_422_counts": {}, "saved_in_attempt": {}}
            await graph.ainvoke(initial, config)
            fenced.set()
            with self.assertRaises(Fenced):
                await graph.ainvoke(None, config)
        finally:
            await handle.close()
            await client.aclose()

    async def test_rework_prompt_includes_previous_findings(self) -> None:
        inst = await asyncio.to_thread(self._start_job)
        task_id, _contract = self._insert_task_row(inst)
        attempt2 = ids.new_attempt_id()
        rework_body = json.dumps(
            {"verdict": "REWORK", "verifier": {"name": "brief_schema", "findings": ["title: fix it"]}}
        )
        _pg.admin_sql(
            self.db,
            f"""
            update work.attempts set state = 'ENDED', outcome = 'submitted',
              submit_response = '{rework_body}'::jsonb
            where task_id = '{task_id}' and n = 1;
            insert into work.attempts (id, task_id, n, fencing_token, state, reserved_usd)
            values ('{attempt2}', '{task_id}', 2, 3, 'ADMITTED', 1.0);
            update work.tasks set fencing_token = 3, attempts_used = 2 where id = '{task_id}';
            """,
        )
        client = await make_http_client(self, invoke_hook=mock_erp_hook)
        _pg.require_runtime_extra()
        handle = await CheckpointerHandle.open(_pg.worker_checkpoint_url(self.db))
        try:
            from aos.worker.graph_runner import run_task_graph

            attempt = await client.claim("worker-test-1", ["task"])
            assert attempt
            resolved = await handle.resolve(attempt)
            ctx = AttemptContext(attempt, client, asyncio.Event())
            script = load_fake_script("request_intake.rework_test.yaml", attempt_n=int(attempt.get("n") or 2))
            model = chat_model_from_script(script)
            result = await run_task_graph(
                attempt=attempt,
                ctx=ctx,
                chat_model=model,
                checkpointer=handle,
                resolved=resolved,
                adapter="fake",
            )
            self.assertEqual(result.get("status"), "completed")
            self.assertGreaterEqual(len(model.fake.prompts), 1)
            blob = json.dumps(model.fake.prompts, default=str)
            self.assertIn("title: fix it", blob)
            thread2 = langgraph_thread_id({"task_id": task_id, "n": 2})
            self.assertEqual(resolved.thread_id, thread2)
        finally:
            await handle.close()
            await client.aclose()

    def test_fake_script_name_by_skill_and_scenario(self) -> None:
        import os

        attempt = {
            "contract": {"kind": "task", "skill": {"name": "supplier_lookup"}},
            "n": 2,
        }
        prev_scenario = os.environ.get("AOS_FAKE_SCENARIO")
        prev_script = os.environ.get("AOS_FAKE_SCRIPT")
        os.environ["AOS_FAKE_SCENARIO"] = "happy"
        os.environ.pop("AOS_FAKE_SCRIPT", None)
        try:
            self.assertEqual(_fake_script_name(attempt, None), "supplier_lookup.happy.yaml")
            self.assertEqual(_fake_script_name({"contract": {"kind": "assist"}}, None), "assist.stream.yaml")
        finally:
            if prev_scenario is None:
                os.environ.pop("AOS_FAKE_SCENARIO", None)
            else:
                os.environ["AOS_FAKE_SCENARIO"] = prev_scenario
            if prev_script is not None:
                os.environ["AOS_FAKE_SCRIPT"] = prev_script
            else:
                os.environ.pop("AOS_FAKE_SCRIPT", None)
        self.assertEqual(_fake_script_name(attempt, "custom.yaml"), "custom.yaml")


if __name__ == "__main__":
    unittest.main()
