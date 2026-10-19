"""Assist graph, FakeRuntime, streaming and budgets (M1-AG-02)."""

from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch

from aos.worker.checkpointer import CheckpointerHandle, langgraph_thread_id
from aos.worker.fake_chat import chat_model_from_script
from aos.worker.http_client import HttpKernelClient
from aos.worker.protocol import AttemptContext
from aos.worker.runner import Worker
from aos.worker.runtime import FakeRuntime
from aos.worker.scripts_loader import load_fake_script

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

        instance_id = await asyncio.to_thread(self._start_job)
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

        # The snapshot names the agent by the Seat's display name, as the live turn event does (not its id).
        snapshot = self.client.get(f"/api/instances/{instance_id}", headers=self._auth("faisal")).json()
        seat_turns = [t for t in snapshot["turns"] if t["author"]["kind"] == "seat"]
        self.assertTrue(seat_turns)
        workers = self.client.get("/api/workspace/digital-workers", headers=self._auth("faisal")).json()["items"]
        display = next(w["display_name"] for w in workers if w["seat"] == seat_turns[0]["author"]["id"])
        self.assertNotEqual(display, seat_turns[0]["author"]["id"])
        self.assertEqual({t["author"]["name"] for t in seat_turns}, {display})

    async def test_step_budget_stops_loop_without_submit(self) -> None:
        outcome = await self._run_fake("assist.loop.yaml", budget_steps=9)
        self.assertEqual(outcome, "failed:budget_exhausted", outcome)
        state = _pg.admin_sql(
            self.db,
            "select state from work.tasks order by updated_at desc limit 1;",
        ).stdout.strip()
        self.assertEqual(state, "EXCEPTION")

    async def test_loop_records_tool_actions(self) -> None:
        await asyncio.to_thread(self._start_job)
        client = await make_http_client(self, invoke_hook=mock_erp_hook)
        _pg.require_runtime_extra()
        handle = await CheckpointerHandle.open(_pg.worker_checkpoint_url(self.db))
        _patch_latest_task_budget(self.db, steps=9)
        try:
            runtime = FakeRuntime(checkpointer=handle, script="assist.loop.yaml")
            worker = Worker("worker-test-1", client, runtime, ("assist",))
            await asyncio.wait_for(worker.run_once(), 60)
        finally:
            await handle.close()
            await client.aclose()
        actions = _pg.admin_sql(
            self.db,
            "select (usage->>'actions')::int from work.attempts order by admitted_at desc limit 1;",
        ).stdout.strip()
        self.assertGreater(int(actions or 0), 0)
        # The script repeats the same call every step; only the first reaches the gateway, the repeats get a note.
        authorized = _pg.admin_sql(
            self.db,
            "select count(*) from evidence.execution_events where event_type = 'ToolAuthorized';",
        ).stdout.strip()
        self.assertEqual(authorized, "1")

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

    async def test_403_tool_not_in_contract_in_next_prompt(self) -> None:
        captured: dict[str, object] = {}
        real_factory = chat_model_from_script

        def capture_model(script):
            model = real_factory(script)
            captured["model"] = model
            return model

        await asyncio.to_thread(self._start_job)
        client = await make_http_client(self, invoke_hook=mock_erp_hook)
        _pg.require_runtime_extra()
        handle = await CheckpointerHandle.open(_pg.worker_checkpoint_url(self.db))
        try:
            with patch("aos.worker.fake_chat.chat_model_from_script", side_effect=capture_model):
                runtime = FakeRuntime(checkpointer=handle, script="assist.forbidden_tool.yaml")
                worker = Worker("worker-test-1", client, runtime, ("assist",))
                outcome = await asyncio.wait_for(worker.run_once(), 120)
                self.assertEqual(outcome, "submitted", outcome)
        finally:
            await handle.close()
            await client.aclose()
        model = captured.get("model")
        self.assertIsNotNone(model)
        prompts = model.fake.prompts  # type: ignore[union-attr]
        self.assertGreaterEqual(len(prompts), 2)
        second = prompts[1]
        blob = json.dumps(second, default=str)
        self.assertIn("not allowed: contract.allowed_tools", blob)

    async def test_checkpoint_after_fake_runtime_run(self) -> None:
        await asyncio.to_thread(self._start_job)
        client = await make_http_client(self, invoke_hook=mock_erp_hook)
        _pg.require_runtime_extra()
        handle = await CheckpointerHandle.open(_pg.worker_checkpoint_url(self.db))
        try:
            runtime = FakeRuntime(checkpointer=handle, script="assist.stream.yaml")
            worker = Worker("worker-test-1", client, runtime, ("assist",))
            self.assertEqual(await asyncio.wait_for(worker.run_once(), 60), "submitted")
        finally:
            await client.aclose()
        row = _pg.admin_sql(
            self.db,
            "select task_id, n from work.attempts order by admitted_at desc limit 1;",
        ).stdout.strip()
        task_id, n = row.split("|")
        thread_id = langgraph_thread_id({"task_id": task_id, "n": int(n)})
        tup = await handle.saver.aget_tuple({"configurable": {"thread_id": thread_id}})
        self.assertIsNotNone(tup, f"no checkpoint for thread {thread_id}")
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
        graph = handle.assist_graph(interrupt_after=["tools"])
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
