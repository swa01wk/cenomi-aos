"""Assist graph, FakeRuntime, streaming and budgets (M1-AG-02)."""

from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch

from aos.worker.checkpointer import CheckpointerHandle, langgraph_thread_id
from aos.worker.errors import ToolInvocationError
from aos.worker.fake_chat import chat_model_from_script
from aos.worker.graphs.assist import build_assist_graph
from aos.worker.http_client import HttpKernelClient
from aos.worker.protocol import AttemptContext
from aos.worker.runner import Worker
from aos.worker.runtime import FakeRuntime
from aos.worker.scripts_loader import load_fake_script
from aos.worker.types import WorkerAttempt  # noqa: F401 — resume test typing

from . import _pg
from .worker_harness import WorkerHarness, make_http_client, mock_erp_hook, settings_with_lease


def _patch_latest_task_budget(db: str, *, steps: int | None = None, tokens: int | None = None) -> None:
    expr = "contract"
    if steps is not None:
        expr = f"jsonb_set({expr}, '{{budget,steps}}', '{int(steps)}'::jsonb, true)"
    if tokens is not None:
        expr = f"jsonb_set({expr}, '{{budget,tokens}}', '{int(tokens)}'::jsonb, true)"
    if expr == "contract":
        return
    sql = (
        f"update work.tasks set contract = {expr} "
        "where id = (select t.id from work.tasks t order by t.created_at desc limit 1);"
    )
    _pg.admin_sql(db, sql)


@unittest.skipUnless(_pg.available(), "no local Postgres")
class AssistGraphTests(WorkerHarness, unittest.IsolatedAsyncioTestCase):
    async def _run_fake(
        self,
        script: str,
        *,
        invoke_hook=mock_erp_hook,
        settings=None,
        budget_steps: int | None = None,
        budget_tokens: int | None = None,
    ) -> str:
        await asyncio.to_thread(self._start_job)
        client = await make_http_client(self, invoke_hook=invoke_hook, settings=settings)
        _pg.require_runtime_extra()
        handle = await CheckpointerHandle.open(_pg.worker_checkpoint_url(self.db))
        try:
            if budget_steps is not None or budget_tokens is not None:
                _patch_latest_task_budget(self.db, steps=budget_steps, tokens=budget_tokens)
            runtime = FakeRuntime(checkpointer=handle, script=script)
            worker = Worker("worker-test-1", client, runtime, ("assist",))
            return await asyncio.wait_for(worker.run_once(), 60)
        finally:
            await handle.close()
            await client.aclose()

    async def test_stream_deltas_then_typed_blocks(self) -> None:
        seqs: list[int] = []

        async def capture(**kwargs):
            seqs.append(int(kwargs["delta_seq"]))

        await asyncio.to_thread(self._start_job)
        client = await make_http_client(self, invoke_hook=mock_erp_hook)
        _pg.require_runtime_extra()
        handle = await CheckpointerHandle.open(_pg.worker_checkpoint_url(self.db))
        try:
            with patch("aos.kernel.worker_events.OutboxHub.publish_delta", new_callable=AsyncMock) as pub:
                pub.side_effect = capture
                runtime = FakeRuntime(checkpointer=handle, script="assist.stream.yaml")
                worker = Worker("worker-test-1", client, runtime, ("assist",))
                outcome = await asyncio.wait_for(worker.run_once(), 60)
                self.assertEqual(outcome, "submitted")
        finally:
            await handle.close()
            await client.aclose()
        self.assertGreaterEqual(len(seqs), 1)
        self.assertEqual(seqs, list(range(len(seqs))))
        turns = _pg.admin_sql(
            self.db,
            "select blocks from work.turns where author_kind = 'seat' order by seq desc limit 1;",
        ).stdout.strip()
        blocks = json.loads(turns)
        self.assertEqual(blocks[0]["kind"], "text")
        self.assertIn("streamed assist reply", blocks[0]["text"])

    async def test_step_budget_stops_loop_without_submit(self) -> None:
        outcome = await self._run_fake("assist.loop.yaml", budget_steps=2)
        self.assertTrue(outcome.startswith("failed:"), outcome)
        self.assertIn("budget_exhausted", outcome)
        state = _pg.admin_sql(
            self.db,
            "select state from work.tasks order by updated_at desc limit 1;",
        ).stdout.strip()
        self.assertEqual(state, "EXCEPTION")

    async def test_budget_cross_on_post_then_fenced_no_submit(self) -> None:
        outcome = await self._run_fake("assist.heavy.yaml", budget_tokens=50, budget_steps=10)
        self.assertNotEqual(outcome, "submitted")
        state = _pg.admin_sql(
            self.db,
            "select state from work.tasks order by updated_at desc limit 1;",
        ).stdout.strip()
        self.assertEqual(state, "EXCEPTION")
        failure = _pg.admin_sql(
            self.db,
            "select failure_class from work.attempts where failure_class is not null order by admitted_at desc limit 1;",
        ).stdout.strip()
        self.assertEqual(failure, "budget_exhausted")

    async def test_tool_timeout_fails_attempt(self) -> None:
        async def slow_hook(**_kw):
            await asyncio.sleep(5.0)

        settings = settings_with_lease(self, 30.0)
        settings = settings.__class__.from_env(
            database_url=settings.database_url,
            packs_dir=settings.packs_dir,
            session_secret=settings.session_secret,
            scheduler_interval_seconds=settings.scheduler_interval_seconds,
            worker_lease_seconds=settings.worker_lease_seconds,
            gateway_timeout_seconds=0.05,
            connector_secrets=settings.connector_secrets,
            connector_urls=settings.connector_urls,
        )
        await asyncio.to_thread(self._start_job)
        client = await make_http_client(self, invoke_hook=slow_hook, settings=settings)
        _pg.require_runtime_extra()
        handle = await CheckpointerHandle.open(_pg.worker_checkpoint_url(self.db))
        try:
            runtime = FakeRuntime(checkpointer=handle, script="assist.loop.yaml")
            worker = Worker("worker-test-1", client, runtime, ("assist",))
            outcome = await asyncio.wait_for(worker.run_once(), 60)
        finally:
            await handle.close()
            await client.aclose()
        self.assertIn("tool_timeout", outcome)

    async def test_403_becomes_worker_note(self) -> None:
        await asyncio.to_thread(self._start_job)
        client = await make_http_client(self, invoke_hook=mock_erp_hook)
        _pg.require_runtime_extra()
        handle = await CheckpointerHandle.open(_pg.worker_checkpoint_url(self.db))
        attempt = await client.claim("worker-test-1", ["assist"])
        assert attempt
        fenced = asyncio.Event()
        ctx = AttemptContext(attempt, client, fenced)

        async def fake_call_tool(tool, args):
            raise ToolInvocationError("denied", code="policy_denied", rule="demo_rule")

        ctx.call_tool = fake_call_tool  # type: ignore[method-assign]
        script = load_fake_script("assist.loop.yaml")
        model = chat_model_from_script(script)
        resolved = await handle.resolve(attempt)
        graph = build_assist_graph(handle.saver, interrupt_after=["tools"])
        config = {
            "configurable": {
                "thread_id": resolved.thread_id,
                "ctx": ctx,
                "chat_model": model,
                "attempt": attempt,
                "adapter": "fake",
            }
        }
        initial = {"ids": {"turn_id": str(attempt.get("turn_id") or "")}, "worker_notes": [], "draft_422_counts": {}, "stream_seq": 0}
        await graph.ainvoke(initial, config)
        snapshot = await graph.aget_state(config)
        notes = snapshot.values.get("worker_notes") or []
        self.assertTrue(any("not allowed: demo_rule" in n for n in notes))
        await handle.close()
        await client.aclose()

    async def test_graph_uses_resolved_thread_id(self) -> None:
        _pg.require_runtime_extra()
        handle = await CheckpointerHandle.open(_pg.worker_checkpoint_url(self.db))
        try:
            attempt: WorkerAttempt = {
                "attempt_id": "att_thr",
                "task_id": "task_thr",
                "instance_id": "inst_thr",
                "n": 4,
                "fencing_token": 1,
                "lease_seconds": 90,
                "kind": "assist",
                "contract": {"contract_hash": "a" * 64},
            }
            resolved = await handle.resolve(attempt)
            self.assertEqual(resolved.thread_id, langgraph_thread_id(attempt))
        finally:
            await handle.close()

    async def test_resume_continues_checkpoint(self) -> None:
        _pg.require_runtime_extra()
        handle = await CheckpointerHandle.open(_pg.worker_checkpoint_url(self.db))
        await asyncio.to_thread(self._start_job)
        client = await make_http_client(self, invoke_hook=mock_erp_hook)
        attempt = await client.claim("worker-test-1", ["assist"])
        assert attempt
        resolved = await handle.resolve(attempt)
        fenced = asyncio.Event()
        ctx = AttemptContext(attempt, client, fenced)
        script = load_fake_script("assist.resume.yaml")
        model = chat_model_from_script(script)
        graph = build_assist_graph(handle.saver, interrupt_after=["tools"])
        config = {
            "configurable": {
                "thread_id": resolved.thread_id,
                "ctx": ctx,
                "chat_model": model,
                "attempt": attempt,
                "adapter": "fake",
            }
        }
        initial = {"ids": {"turn_id": str(attempt.get("turn_id") or "")}, "worker_notes": [], "draft_422_counts": {}, "stream_seq": 0}
        await graph.ainvoke(initial, config)
        tup = await handle.saver.aget_tuple({"configurable": {"thread_id": resolved.thread_id}})
        assert tup is not None
        cp_id = tup.config["configurable"]["checkpoint_id"]
        config["configurable"]["checkpoint_id"] = cp_id
        final = await graph.ainvoke(None, config)
        self.assertIn("agent_result", final)
        await handle.close()
        await client.aclose()


if __name__ == "__main__":
    unittest.main()
