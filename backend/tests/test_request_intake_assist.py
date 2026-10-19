"""request_intake on the assist graph (M1-AG-03)."""

from __future__ import annotations

import asyncio
import json
import os
import unittest
import uuid
from typing import Any
from aos.worker.checkpointer import CheckpointerHandle
from aos.worker.graphs.assist import tools_node
from aos.worker.graphs.state import AssistGraphState
from aos.worker.http_client import HttpKernelClient
from aos.worker.protocol import AttemptContext
from aos.worker.runner import Worker
from aos.worker.runtime import FakeRuntime, LangGraphRuntime

from . import _pg
from .test_worker_api import WorkerHarness
from .worker_harness import make_http_client, mock_erp_hook


class _RecordingKernel:
    """Wraps HttpKernelClient and records selected calls."""

    def __init__(self, inner: HttpKernelClient) -> None:
        self._inner = inner
        self.calls: list[str] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def submit_result(self, attempt, result):  # type: ignore[no-untyped-def]
        self.calls.append("submit_result")
        return await self._inner.submit_result(attempt, result)

    async def ask_questions(self, attempt, *, blocks, questions=None):  # type: ignore[no-untyped-def]
        self.calls.append("ask_questions")
        return await self._inner.ask_questions(attempt, blocks=blocks, questions=questions)

    async def aclose(self) -> None:
        await self._inner.aclose()


@unittest.skipUnless(_pg.available(), "no local Postgres")
class RequestIntakeAssistTests(WorkerHarness, unittest.IsolatedAsyncioTestCase):
    async def _client(self) -> _RecordingKernel:
        return await make_http_client(self, invoke_hook=mock_erp_hook)  # type: ignore[return-value]

    async def _run_fake_once(self, client: HttpKernelClient, script: str) -> str:
        _pg.require_runtime_extra()
        handle = await CheckpointerHandle.open(_pg.worker_checkpoint_url(self.db))
        try:
            runtime = FakeRuntime(checkpointer=handle, script=script)
            worker = Worker("worker-test-1", client, runtime, ("assist",))
            return await asyncio.wait_for(worker.run_once(), 120)
        finally:
            await handle.close()
            await client.aclose()

    async def test_happy_two_attempts_brief_versions(self) -> None:
        inst = await asyncio.to_thread(self._start_job)
        client = await make_http_client(self, invoke_hook=mock_erp_hook)
        outcome1 = await self._run_fake_once(client, "request_intake.happy.yaml")
        self.assertEqual(outcome1, "waiting", outcome1)
        task_state = _pg.admin_sql(
            self.db,
            "select state from work.tasks order by updated_at desc limit 1;",
        ).stdout.strip()
        self.assertEqual(task_state, "WAITING_INPUT")
        attempt1 = _pg.admin_sql(
            self.db,
            "select id from work.attempts where task_id = (select id from work.tasks order by updated_at desc limit 1)"
            " order by n asc limit 1;",
        ).stdout.strip()
        v1_row = _pg.admin_sql(
            self.db,
            f"select artifact_id, version, produced_by from work.artifact_versions"
            f" where produced_by = '{attempt1}' order by version asc limit 1;",
        ).stdout.strip()
        self.assertTrue(v1_row)
        artifact_id, ver1, _ = v1_row.split("|")
        self.assertEqual(ver1, "1")

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

        client2 = await make_http_client(self, invoke_hook=mock_erp_hook)
        outcome2 = await self._run_fake_once(client2, "request_intake.happy.yaml")
        self.assertEqual(outcome2, "submitted", outcome2)
        attempt2 = _pg.admin_sql(
            self.db,
            "select id from work.attempts where task_id = (select id from work.tasks order by updated_at desc limit 1)"
            " order by n desc limit 1;",
        ).stdout.strip()
        v2 = _pg.admin_sql(
            self.db,
            f"select artifact_id, version, produced_by, inputs::text from work.artifact_versions"
            f" where artifact_id = '{artifact_id}' and version = 2;",
        ).stdout.strip()
        self.assertTrue(v2)
        parts = v2.split("|")
        self.assertEqual(parts[0], artifact_id)
        self.assertEqual(parts[1], "2")
        self.assertEqual(parts[2], attempt2)
        inputs = json.loads(parts[3])
        self.assertTrue(any(i.get("artifact_id") == artifact_id and i.get("version") == 1 for i in inputs))

        # The requester sees who produced each version by the Seat's display name, not the attempt id.
        workers = self.client.get("/api/workspace/digital-workers", headers=self._auth("faisal")).json()["items"]
        display = workers[0]["display_name"]
        version = self.client.get(f"/api/artifacts/{artifact_id}/versions/2", headers=self._auth("faisal")).json()
        self.assertEqual(version["produced_by"], {"kind": "attempt", "id": attempt2, "name": display})
        summary = self.client.get(f"/api/artifacts/{artifact_id}", headers=self._auth("faisal")).json()
        self.assertEqual({v["by"] for v in summary["versions"]}, {display})

    async def test_ask_question_ends_without_submit(self) -> None:
        await asyncio.to_thread(self._start_job)
        inner = await make_http_client(self, invoke_hook=mock_erp_hook)
        rec = _RecordingKernel(inner)
        _pg.require_runtime_extra()
        handle = await CheckpointerHandle.open(_pg.worker_checkpoint_url(self.db))
        try:
            runtime = FakeRuntime(checkpointer=handle, script="request_intake.happy.yaml")
            worker = Worker("worker-test-1", rec, runtime, ("assist",))
            outcome = await asyncio.wait_for(worker.run_once(), 120)
            self.assertEqual(outcome, "waiting")
            self.assertIn("ask_questions", rec.calls)
            self.assertNotIn("submit_result", rec.calls)
        finally:
            await handle.close()
            await rec.aclose()

    async def test_commands_carry_typed_schemas(self) -> None:
        await asyncio.to_thread(self._start_job)
        client = await make_http_client(self, invoke_hook=mock_erp_hook)
        attempt = await client.claim("worker-test-1", ["assist"])
        assert attempt
        envelope = await client.assemble_context(attempt, reason="start")
        await client.aclose()
        names = {c["name"] for c in envelope.get("commands") or []}
        self.assertNotIn("read_artifact", names)
        save = next(c for c in envelope["commands"] if c["name"] == "save_draft")
        props = save["input_schema"].get("properties") or {}
        self.assertIn("content", props)
        self.assertNotIn("required", props.get("content") or {})
        content_props = (props.get("content") or {}).get("properties") or {}
        self.assertIn("delivery_date", content_props)
        self.assertEqual(content_props["delivery_date"].get("format"), "date")
        ask = next(c for c in envelope["commands"] if c["name"] == "ask_question")
        qschema = ask["input_schema"]["properties"]["questions"]
        self.assertEqual(qschema.get("maxItems"), 3)

@unittest.skipUnless(_pg.available() and os.environ.get("AOS_REAL_MODEL") == "1", "manual real-model smoke")
class RequestIntakeRealModelSmoke(WorkerHarness, unittest.IsolatedAsyncioTestCase):
    def _start_job_trolley_message(self) -> None:
        from .test_worker_api import SEAT, WORKFLOW

        self._activate_seat()
        r = self.client.post(
            "/api/instances",
            headers={**self._auth("faisal"), "Idempotency-Key": str(uuid.uuid4())},
            json={
                "seat": SEAT,
                "workflow": WORKFLOW,
                "first_message": "We need four heavy-duty cleaning trolleys for custodial work.",
            },
        )
        self.assertEqual(r.status_code, 201, r.text)

    async def test_first_brief_draft_omits_delivery_date(self) -> None:
        await asyncio.to_thread(self._start_job_trolley_message)
        client = await make_http_client(self, invoke_hook=mock_erp_hook)
        _pg.require_runtime_extra()
        handle = await CheckpointerHandle.open(_pg.worker_checkpoint_url(self.db))
        try:
            runtime = LangGraphRuntime(checkpointer=handle)
            worker = Worker("worker-test-1", client, runtime, ("assist",))
            outcome = await asyncio.wait_for(worker.run_once(), 180)
            self.assertIn(outcome, ("waiting", "submitted"), outcome)
        finally:
            await handle.close()
            await client.aclose()
        row = _pg.admin_sql(
            self.db,
            "select content::text from work.artifact_versions av"
            " join work.artifacts a on a.id = av.artifact_id"
            " where a.artifact_type = 'brief' order by av.version asc limit 1;",
        ).stdout.strip()
        if not row:
            print("real-model smoke: model did not save a brief draft in one turn")
            return
        content = json.loads(row)
        self.assertNotIn("delivery_date", content)
        self.assertNotIn("delivery_site", content)


class AssistToolsNodeTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _ctx(calls: list[str]):
        class Ctx:
            attempt_closed = False
            envelope = {"artifacts": []}
            contract_bundle = {
                "contract": {
                    "expected_outputs": [{"artifact_type": "brief", "cardinality": "one"}],
                }
            }
            attempt = {"contract": {"expected_outputs": [{"artifact_type": "brief"}]}}

            def check(self) -> None:
                return None

            async def post_events(self, **kwargs: Any) -> None:
                return None

            async def save_draft(self, body: dict[str, Any]) -> dict[str, Any]:
                calls.append("save_draft")
                return {"artifact_id": "art-1", "version": 1, "artifact_type": "brief"}

            async def call_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
                calls.append(f"tool:{name}")
                return {"content": {}}

            async def ask_questions(self, blocks, questions=None) -> dict[str, Any]:
                calls.append("ask_questions")
                self.attempt_closed = True
                return {}

            def record_tool_action(self) -> None:
                return None

        return Ctx()

    async def _run(self, pending: list[dict[str, Any]]) -> tuple[list[str], dict[str, Any]]:
        calls: list[str] = []
        state: AssistGraphState = {"pending_tool_calls": pending, "draft_422_counts": {}, "saved_in_attempt": {}}
        out = await tools_node(state, {"configurable": {"ctx": self._ctx(calls)}})
        return calls, out

    async def test_tool_batch_runs_ask_question_last(self) -> None:
        """Kernel tools keep model order; the first ask_question runs last; extra asks are dropped."""
        calls, out = await self._run(
            [
                {"name": "ask_question", "args": {"questions": ["Q?"]}},
                {"name": "save_draft", "args": {"content": {"title": "T"}}},
                {"name": "ask_question", "args": {"questions": ["Again?"]}},
            ]
        )
        self.assertTrue(out.get("ended_needs_input"))
        self.assertEqual(calls, ["save_draft", "ask_questions"])

    async def test_question_beside_a_lookup_is_held(self) -> None:
        """A question written beside a lookup waits for its result: the lookups run, the attempt goes on."""
        calls, out = await self._run(
            [
                {"name": "ask_question", "args": {"questions": ["Q?"]}},
                {"name": "browse_categories", "args": {"query": "x"}},
                {"name": "save_draft", "args": {"content": {"title": "T"}}},
                {"name": "browse_categories", "args": {"query": "after"}},
            ]
        )
        self.assertFalse(out.get("ended_needs_input"))
        self.assertEqual(calls, ["tool:browse_categories", "save_draft", "tool:browse_categories"])
        self.assertTrue(any("ask_question was held" in n for n in out["worker_notes"]))

if __name__ == "__main__":
    unittest.main()
