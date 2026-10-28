"""M2-AG-02: the supplier_lookup and rfq_draft Tasks run through the Task graph with the fake model's scripts."""

from __future__ import annotations

import asyncio
import json
import unittest
import uuid

from langchain_core.messages import HumanMessage
from psycopg_pool import AsyncConnectionPool

from aos.kernel.readiness import run_readiness_tick
from aos.worker.checkpointer import CheckpointerHandle
from aos.worker.draft_body import build_save_draft_body, draft_slot
from aos.worker.fake_chat import observed_receipts, resolve_receipts
from aos.worker.runner import Worker
from aos.worker.runtime import FakeRuntime
from aos.worker.scripts_loader import task_script
from aos.worker.untrusted import format_observation_for_context

from . import _pg
from .test_task_graph import _RecordingKernel
from .test_worker_api import ORG, WorkerHarness
from .worker_harness import make_http_client, mock_erp_hook

SHORTLIST = ["SUP-10482", "SUP-10217", "SUP-10355"]


class _Kernel(_RecordingKernel):
    def __init__(self, inner) -> None:  # type: ignore[no-untyped-def]
        super().__init__(inner)
        self.failures: list[str] = []

    async def fail_attempt(self, attempt, failure_class, message):  # type: ignore[no-untyped-def]
        self.failures.append(f"{failure_class}: {message}")
        return await self._inner.fail_attempt(attempt, failure_class, message)


class WorkerPartsTests(unittest.TestCase):
    def test_observations_show_their_receipt(self) -> None:
        obs = {"tool": "lookup", "args": {"id": "A-1"}, "untrusted": True, "content": {"x": 1}, "receipt_ref": "r1"}
        self.assertIn('receipt="r1"', format_observation_for_context(obs))
        self.assertTrue(format_observation_for_context({**obs, "untrusted": False}).endswith("[receipt r1]"))
        self.assertNotIn("receipt", format_observation_for_context({"tool": "lookup", "args": {}, "content": "x"}))

    def test_receipt_placeholders_take_the_latest_matching_result(self) -> None:
        lines = [
            format_observation_for_context({"tool": "search", "args": {"q": "a"}, "untrusted": True, "content": [],
                                            "receipt_ref": "r-search"}),
            format_observation_for_context({"tool": "history", "args": {"id": "A-1"}, "untrusted": True,
                                            "content": {}, "receipt_ref": "r-a1"}),
            format_observation_for_context({"tool": "history", "args": {"id": "A-2"}, "content": {},
                                            "receipt_ref": "r-a2"}),
        ]
        receipts = observed_receipts([HumanMessage(content=json.dumps({"tool_observations_rendered": lines}))])
        args = {"rows": [{"sources": ["{{receipt:search}}", "{{receipt:history:A-1}}", "{{receipt:history:A-2}}",
                                      "{{receipt:history}}", "{{receipt:other}}"]}]}
        self.assertEqual(
            resolve_receipts(args, receipts)["rows"][0]["sources"],
            ["r-search", "r-a1", "r-a2", "r-a2", "{{receipt:other}}"],
        )

    def test_keyed_drafts_are_tracked_per_item(self) -> None:
        contract = {"expected_outputs": [{"artifact_type": "email"}]}
        envelope = {"artifacts": [
            {"artifact_type": "email", "artifact_id": "a1", "version": 2, "key": "K1", "content": {"to": "x"}},
            {"artifact_type": "email", "artifact_id": "a2", "version": 1, "key": "K2", "content": {"to": "y"}},
        ]}
        body = build_save_draft_body(contract=contract, envelope=envelope, model_args={"key": "K2", "content": {
            "body": "b"}}, saved_in_attempt={})
        self.assertEqual((body["key"], body["artifact_id"], body["base_version"]), ("K2", "a2", 1))
        self.assertEqual(body["content"], {"to": "y", "body": "b"})
        fresh = build_save_draft_body(contract=contract, envelope=envelope, model_args={"key": "K3", "content": {
            "to": "z"}}, saved_in_attempt={})
        self.assertNotIn("artifact_id", fresh)
        saved = {draft_slot("email", "K1"): {"artifact_id": "a1", "version": 3, "content": {"to": "x2"}}}
        again = build_save_draft_body(contract=contract, envelope=envelope, model_args={"key": "K1", "content": {
            "body": "c"}}, saved_in_attempt=saved)
        self.assertEqual((again["base_version"], again["content"]), (3, {"to": "x2", "body": "c"}))

    def test_scripts_are_found_by_template_then_skill(self) -> None:
        def contract(template: str, skill: str) -> dict:
            return {"kind": "task", "template": template, "skill": {"name": skill}}

        self.assertEqual(task_script(contract("rfq_draft", "rfq_authoring"), "leak"), "rfq_draft.leak.yaml")
        self.assertEqual(task_script(contract("supplier_lookup", "supplier_lookup"), "leak"),
                         "supplier_lookup.happy.yaml", "a Task without the scenario runs happy")
        self.assertIsNone(task_script(contract("rfq_send", "rfq_authoring")), "the send Task has no script yet")
        runtime = FakeRuntime(checkpointer=None, scenario="leak")  # type: ignore[arg-type]
        self.assertEqual(runtime._script_name({"contract": contract("rfq_draft", "rfq_authoring")}),
                         "rfq_draft.leak.yaml")


@unittest.skipUnless(_pg.available(), "no local Postgres")
class TaskSkillTests(WorkerHarness, unittest.IsolatedAsyncioTestCase):
    INTAKE_TASK = True

    def sql(self, query: str) -> str:
        return _pg.admin_sql(self.db, query).stdout.strip()

    def task_state(self, inst: str, template: str) -> str:
        return self.sql(
            f"select state from work.tasks where instance_id = '{inst}' and template = '{template}'"
            " order by created_at desc limit 1;"
        )

    def instance(self, inst: str, person: str) -> dict:
        r = self.client.get(f"/api/instances/{inst}", headers=self._auth(person))
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def open_decision(self, inst: str, event: str) -> str:
        return self.sql(
            f"select id from work.pending_items where instance_id = '{inst}' and status = 'open'"
            f" and kind = 'decision' and event = '{event}';"
        )

    def decide(self, inst: str, event: str, person: str, artifact_type: str, **extra) -> dict:
        pending = self.open_decision(inst, event)
        self.assertTrue(pending, f"{event} is open")
        version = int(self.sql(
            f"select latest_version from work.artifacts where instance_id = '{inst}'"
            f" and artifact_type = '{artifact_type}';"
        ))
        r = self.client.post(
            f"/api/pending/{pending}/decide",
            headers={**self._auth(person), "Idempotency-Key": str(uuid.uuid4())},
            json={
                "value": "confirm",
                "expected_version": self.instance(inst, person)["version"],
                "artifact_version": version,
                **extra,
            },
        )
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    async def tick(self) -> None:
        pool = AsyncConnectionPool(_pg.kernel_url(self.db), min_size=1, max_size=2, open=False)
        await pool.open(wait=True, timeout=15)
        try:
            await run_readiness_tick(pool, org=ORG, packs_dir=self.packs)
        finally:
            await pool.close()

    async def run_worker(self, rec: _Kernel, scenario: str | None = None) -> str:
        _pg.require_runtime_extra()
        handle = await CheckpointerHandle.open(_pg.worker_checkpoint_url(self.db))
        try:
            runtime = FakeRuntime(checkpointer=handle, scenario=scenario)
            worker = Worker("worker-test-1", rec, runtime, ("task",))
            outcome = await asyncio.wait_for(worker.run_once(), 120)
        finally:
            await handle.close()
        return outcome if outcome != "failed:internal" else f"{outcome} {rec.failures[-1:]}"

    async def recording_client(self) -> _Kernel:
        rec = _Kernel(await make_http_client(self, invoke_hook=mock_erp_hook))
        self.addAsyncCleanup(rec._inner.aclose)
        return rec

    def output_rows(self, inst: str, artifact_type: str) -> list[tuple[str, int, dict, dict]]:
        """(key, version, content, verification) of the latest version of each artifact of the type."""
        out = self.sql(
            "select json_build_object('key', a.key, 'version', v.version, 'content', v.content,"
            " 'verification', v.verification) from work.artifacts a join work.artifact_versions v"
            " on v.artifact_id = a.id and v.version = a.latest_version"
            f" where a.instance_id = '{inst}' and a.artifact_type = '{artifact_type}' order by a.key;"
        )
        rows = [json.loads(line) for line in out.splitlines() if line]
        return [(r["key"], r["version"], r["content"], r["verification"] or {}) for r in rows]

    async def reach_shortlisting(self, rec: _Kernel) -> str:
        """Intake asks, Faisal answers, the brief passes, Faisal confirms it, the supplier search runs."""
        inst = await asyncio.to_thread(self._start_job)
        self.assertEqual(await self.run_worker(rec), "waiting")
        self.assertEqual(self.task_state(inst, "supplier_lookup"), "CREATED", "the brief named a category")
        await asyncio.to_thread(
            self.client.post,
            f"/api/instances/{inst}/turns",
            headers={**self._auth("faisal"), "Idempotency-Key": str(uuid.uuid4())},
            json={"text": "North warehouse by 20 November, budget 15000", "client_turn_id": str(uuid.uuid4())},
        )
        self.assertEqual(await self.run_worker(rec), "submitted")
        self.assertEqual(self.task_state(inst, "request_intake"), "COMPLETED")
        await asyncio.to_thread(self.decide, inst, "decision.brief_confirmed", "faisal", "brief")
        self.assertEqual(self.instance(inst, "faisal")["state"], "shortlisting")

        await self.tick()
        self.assertEqual(await self.run_worker(rec), "submitted")
        self.assertEqual(self.task_state(inst, "supplier_lookup"), "COMPLETED")
        return inst

    async def reach_rfq_drafting(self, rec: _Kernel) -> str:
        inst = await self.reach_shortlisting(rec)
        r = await asyncio.to_thread(
            self.client.post,
            f"/api/instances/{inst}/claim",
            headers=self._auth("noura"),
            json={"role": "buyer", "expected_version": self.instance(inst, "faisal")["version"]},
        )
        self.assertEqual(r.status_code, 200, r.text)
        await asyncio.to_thread(
            self.decide, inst, "decision.shortlist_confirmed", "noura", "supplier_list", selection=SHORTLIST
        )
        self.assertEqual(self.instance(inst, "noura")["state"], "rfq_drafting")
        await self.tick()
        return inst

    async def test_supplier_lookup_ranks_with_its_own_receipts(self) -> None:
        rec = await self.recording_client()
        inst = await self.reach_shortlisting(rec)

        [(key, version, content, verification)] = self.output_rows(inst, "supplier_list")
        self.assertEqual((key, version), ("", 1))
        rows = content["rows"]
        self.assertEqual([r["supplier_id"] for r in rows],
                         ["SUP-10482", "SUP-10217", "SUP-10355", "SUP-10790", "SUP-10611"])
        receipts = set(self.sql(
            "select attributes->>'receipt_ref' from evidence.execution_events where event_type = 'ToolCompleted'"
            f" and task_id = (select id from work.tasks where instance_id = '{inst}' and template = 'supplier_lookup')"
            " and attributes->>'receipt_ref' is not null;"
        ).splitlines())
        self.assertEqual(len(receipts), 6, "one search and five history reads")
        for row in rows:
            self.assertEqual(len(row["sources"]), 2)
            self.assertLessEqual(set(row["sources"]), receipts, "placeholders became this Task's receipts")
        self.assertEqual(verification.get("verdict"), "PASS")
        self.assertEqual(verification.get("verifier"), "sources_cited")
        self.assertTrue(self.open_decision(inst, "decision.shortlist_confirmed") == "",
                        "the shortlist waits for a buyer to claim the job")

    async def test_rfq_draft_writes_one_email_per_shortlisted_supplier(self) -> None:
        rec = await self.recording_client()
        await self.reach_rfq_drafting(rec)
        attempt = await rec.claim("worker-test-1", ["task"])
        assert attempt is not None
        self.assertEqual(attempt["contract"]["template"], "rfq_draft")
        envelope = await rec.assemble_context(attempt, reason="start")
        [listing] = [a for a in envelope["artifacts"] if a["artifact_type"] == "supplier_list"]
        self.assertEqual([r["supplier_id"] for r in listing["content"]["rows"]], SHORTLIST,
                         "the drafting Task sees only the shortlisted rows")
        [brief] = [a for a in envelope["artifacts"] if a["artifact_type"] == "brief"]
        self.assertNotIn("budget_guidance", brief["content"])
        self.assertNotIn("15000", json.dumps(envelope), "the budget is not in the drafting Task's context at all")

    async def test_per_item_drafts_need_the_item_key(self) -> None:
        rec = await self.recording_client()
        inst = await self.reach_rfq_drafting(rec)
        attempt = await rec.claim("worker-test-1", ["task"])
        assert attempt is not None
        save = attempt["contract"]
        self.assertEqual(save["template"], "rfq_draft")
        content = {"supplier_id": "SUP-10482", "to": "sales@najd.example", "subject": "RFQ", "body": "Hello"}

        def post(body: dict):  # type: ignore[no-untyped-def]
            return self.client.post(
                f"/api/worker/attempts/{attempt['attempt_id']}/drafts",
                headers={**self.worker_auth(), "X-AOS-Fencing-Token": str(attempt["fencing_token"])},
                json={"artifact_type": "rfq_email", "inputs": [], **body},
            )

        for body in ({"content": content}, {"content": content, "key": "SUP-10217"}):
            r = await asyncio.to_thread(post, body)
            self.assertEqual(r.status_code, 422, r.text)
            self.assertEqual(r.json()["title"], "Draft key is invalid")
        r = await asyncio.to_thread(post, {"content": content, "key": "SUP-10482"})
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual(
            self.sql(f"select key || '|' || name from work.artifacts where instance_id = '{inst}'"
                     " and artifact_type = 'rfq_email';"),
            "SUP-10482|Rfq Email SUP-10482",
        )

    async def test_rfq_draft_happy(self) -> None:
        rec = await self.recording_client()
        inst = await self.reach_rfq_drafting(rec)
        self.assertEqual(await self.run_worker(rec), "submitted")
        self.assertEqual(self.task_state(inst, "rfq_draft"), "COMPLETED")
        emails = self.output_rows(inst, "rfq_email")
        self.assertEqual([e[0] for e in emails], sorted(SHORTLIST))
        for key, version, content, verification in emails:
            self.assertEqual((content["supplier_id"], version), (key, 1))
            self.assertEqual(verification.get("verdict"), "PASS")
        self.assertEqual(self.instance(inst, "noura")["state"], "rfq_sending")

    async def test_rfq_draft_leak_is_reworked_then_passes(self) -> None:
        rec = await self.recording_client()
        inst = await self.reach_rfq_drafting(rec)
        self.assertEqual(await self.run_worker(rec, scenario="leak"), "submitted")
        self.assertEqual(self.task_state(inst, "rfq_draft"), "READY", "leak_check sent it back")
        expected = [f"rfq_email[{sid}].body contains the value of brief.budget_guidance." for sid in SHORTLIST]
        for _key, version, _content, verification in self.output_rows(inst, "rfq_email"):
            self.assertEqual(version, 1)
            self.assertEqual(verification.get("verdict"), "REWORK")
            self.assertEqual(sorted(verification.get("findings")), sorted(expected))
            self.assertNotIn("15", json.dumps(verification), "findings never quote the value")
        self.assertEqual(self.instance(inst, "noura")["state"], "rfq_drafting")

        await self.tick()
        self.assertEqual(await self.run_worker(rec, scenario="leak"), "submitted")
        self.assertEqual(self.task_state(inst, "rfq_draft"), "COMPLETED")
        for _key, version, content, verification in self.output_rows(inst, "rfq_email"):
            self.assertEqual(version, 2)
            self.assertNotIn("15,000", content["body"])
            self.assertEqual(verification.get("verdict"), "PASS")
        self.assertEqual(self.instance(inst, "noura")["state"], "rfq_sending")


if __name__ == "__main__":
    unittest.main()
