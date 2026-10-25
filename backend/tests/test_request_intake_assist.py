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

    async def test_sourcing_assist_contract_is_read_only(self) -> None:
        await asyncio.to_thread(self._start_assist_job)
        client = await make_http_client(self, invoke_hook=mock_erp_hook)
        attempt = await client.claim("worker-test-1", ["assist"])
        assert attempt
        envelope = await client.assemble_context(attempt, reason="start")
        await client.aclose()
        allowed = {t["name"] for t in (attempt.get("contract") or {}).get("allowed_tools") or []}
        self.assertIn("read_artifact", allowed)
        self.assertEqual((attempt.get("contract") or {}).get("skill", {}).get("name"), "sourcing_assist")
        names = {c["name"] for c in envelope.get("commands") or []}
        self.assertNotIn("save_draft", names)
        self.assertNotIn("ask_question", names)

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
            worker = Worker("worker-test-1", client, runtime, ("assist", "task"))
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

    async def test_actions_are_recorded_and_an_identical_save_is_skipped(self) -> None:
        """Each step starts from the envelope, so the reply's own actions are carried for the next step."""
        draft = {"name": "save_draft", "args": {"content": {"title": "T"}}}
        calls, out = await self._run([draft, {"name": "browse_categories", "args": {"query": "x"}}, draft])
        self.assertEqual(calls, ["save_draft", "tool:browse_categories"])
        actions = out["actions_this_reply"]
        self.assertEqual(len(actions), 2)
        self.assertIn("saved brief v1", actions[0])
        self.assertIn('browse_categories({"query": "x"})', actions[1])
        self.assertTrue(any("save_draft skipped" in n for n in out["worker_notes"]))

if __name__ == "__main__":
    unittest.main()
