"""Worker protocol over HTTP + Postgres (M0 scenarios, M1-AG-01 client)."""

from __future__ import annotations

import asyncio
import time
import unittest

from aos.worker.default_fake import minimal_agent_result
from aos.worker.protocol import AttemptFailed
from aos.worker.runner import Worker
from aos.worker.runtime import FakeRuntime
from aos.worker.types import WorkerAttempt

from . import _pg
from .worker_harness import WorkerHarness, make_http_client, settings_with_lease


async def _ok_step(attempt: WorkerAttempt, ctx):
    await ctx.post_events(events=[{"event_type": "AgentStarted", "redacted_summary": "protocol test"}])
    return minimal_agent_result(attempt)


@unittest.skipUnless(_pg.available(), "no local Postgres")
class WorkerProtocolTests(WorkerHarness, unittest.IsolatedAsyncioTestCase):
    async def test_happy_path_submits_once(self) -> None:
        await asyncio.to_thread(self._start_job)
        client = await make_http_client(self, "w1")
        worker = Worker("w1", client, FakeRuntime([_ok_step]), ("assist",))
        self.assertEqual(await worker.run_once(), "submitted")
        self.assertEqual(await worker.run_once(), "idle")
        await client.aclose()

    async def test_heartbeats_keep_attempt_alive_past_claim_lease(self) -> None:
        await asyncio.to_thread(self._start_job)
        lease = 3.0
        client = await make_http_client(self, "w1", settings=settings_with_lease(self, lease))
        release = asyncio.Event()

        async def slow_step(attempt: WorkerAttempt, ctx):
            while not release.is_set():
                await asyncio.sleep(0.05)
            return minimal_agent_result(attempt)

        worker = Worker("w1", client, FakeRuntime([slow_step]), ("assist",), heartbeat_enabled=True)
        run_task = asyncio.create_task(worker.run_once())

        while client.heartbeat_count < 2:
            await asyncio.sleep(0.05)
        claim_mono = time.monotonic()
        while time.monotonic() < claim_mono + lease:
            await asyncio.sleep(0.05)
        await asyncio.to_thread(self._run_tick)
        release.set()
        self.assertEqual(await run_task, "submitted")
        await client.aclose()

    async def test_heartbeats_disabled_fenced_after_expiry_tick(self) -> None:
        await asyncio.to_thread(self._start_job)
        lease = 3.0
        client = await make_http_client(self, "w1", settings=settings_with_lease(self, lease))
        release = asyncio.Event()

        async def slow_step(attempt: WorkerAttempt, ctx):
            while not release.is_set():
                await asyncio.sleep(0.05)
            return minimal_agent_result(attempt)

        worker = Worker("w1", client, FakeRuntime([slow_step]), ("assist",), heartbeat_enabled=False)
        run_task = asyncio.create_task(worker.run_once())
        claim_mono = time.monotonic()
        while time.monotonic() < claim_mono + lease:
            await asyncio.sleep(0.05)
        await asyncio.to_thread(self._run_tick)
        release.set()
        self.assertEqual(await run_task, "fenced")
        await client.aclose()

    async def test_stalled_worker_is_fenced_and_cannot_commit(self) -> None:
        await asyncio.to_thread(self._start_job)
        client_a = await make_http_client(self, "A", settings=settings_with_lease(self, 0.35))
        client_b = await make_http_client(self, "B", settings=settings_with_lease(self, 0.35))
        gate = asyncio.Event()

        async def stalls(attempt: WorkerAttempt, ctx):
            await gate.wait()
            return minimal_agent_result(attempt)

        worker_a = Worker("A", client_a, FakeRuntime([stalls]), ("assist",), heartbeat_enabled=False)
        worker_b = Worker("B", client_b, FakeRuntime([_ok_step]), ("assist",))

        task_a = asyncio.create_task(worker_a.run_once())
        await asyncio.sleep(0.45)
        await asyncio.to_thread(self._run_tick)
        self.assertEqual(await worker_b.run_once(), "submitted")
        gate.set()
        self.assertEqual(await task_a, "fenced")
        await client_a.aclose()
        await client_b.aclose()

    async def test_failures_are_classified(self) -> None:
        await asyncio.to_thread(self._start_job)

        async def bad(attempt: WorkerAttempt, ctx):
            raise AttemptFailed("invalid_output", "output did not match the brief schema")

        client = await make_http_client(self, "w1")
        worker = Worker("w1", client, FakeRuntime([bad]), ("assist",))
        self.assertEqual(await worker.run_once(), "failed:invalid_output")
        await client.aclose()

    async def test_unexpected_errors_are_internal_not_retried(self) -> None:
        await asyncio.to_thread(self._start_job)

        async def boom(attempt: WorkerAttempt, ctx):
            raise RuntimeError("connector exploded")

        client = await make_http_client(self, "w1")
        worker = Worker("w1", client, FakeRuntime([boom]), ("assist",))
        self.assertEqual(await worker.run_once(), "failed:internal")
        task_id = _pg.admin_sql(self.db, "select id from work.tasks order by created_at desc limit 1;").stdout.strip()
        state = _pg.admin_sql(self.db, f"select state from work.tasks where id = '{task_id}';").stdout.strip()
        self.assertEqual(state, "EXCEPTION")
        admitted = _pg.admin_sql(
            self.db,
            f"select count(*) from work.attempts where task_id = '{task_id}' and state = 'ADMITTED';",
        ).stdout.strip()
        self.assertEqual(admitted, "0")
        await client.aclose()


class FakeModelTests(unittest.TestCase):
    def test_scripted_turns_in_order(self) -> None:
        from aos.worker.fake_model import FakeModel, ScriptedTurn

        m = FakeModel([ScriptedTurn(tool_calls=[{"name": "search_suppliers"}]), ScriptedTurn(text="done")])
        self.assertEqual(m.invoke(["hi"]).tool_calls[0]["name"], "search_suppliers")
        self.assertEqual(m.invoke(["next"]).text, "done")
        with self.assertRaises(RuntimeError):
            m.invoke(["more"])
