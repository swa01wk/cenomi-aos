"""FakeRuntime E2E and lease fencing via HTTP worker."""

from __future__ import annotations

import asyncio
import unittest

from aos.worker.default_fake import minimal_agent_result
from aos.worker.http_client import HttpKernelClient
from aos.worker.runner import Worker
from aos.worker.runtime import FakeRuntime
from aos.worker.types import WorkerAttempt

from . import _pg
from .worker_harness import WorkerHarness, make_http_client, settings_with_lease


@unittest.skipUnless(_pg.available(), "no local Postgres")
class WorkerRuntimeTests(WorkerHarness, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.setUp()

    async def test_fake_runtime_call_tool_and_submit(self) -> None:
        self._start_job()

        async def script(attempt: WorkerAttempt, ctx):
            await ctx.get_contract()
            await ctx.assemble_context(reason="start")
            await ctx.call_tool("browse_categories", {"query": "chair"})
            return minimal_agent_result(attempt, text="Listed categories.")

        client = make_http_client(self)
        worker = Worker("worker-test-1", client, FakeRuntime([script]), ("assist",))
        self.assertEqual(await worker.run_once(), "submitted")
        await client.aclose()

    async def test_lease_expiry_cancels_runtime_no_submit(self) -> None:
        self._start_job()
        client = make_http_client(self, settings=settings_with_lease(self, 2.0))
        block = asyncio.Event()
        submit_calls = 0
        real_submit = client.submit_result

        async def counting_submit(attempt, result):
            nonlocal submit_calls
            submit_calls += 1
            return await real_submit(attempt, result)

        client.submit_result = counting_submit  # type: ignore[method-assign]

        async def blocked(attempt: WorkerAttempt, ctx):
            await block.wait()
            return minimal_agent_result(attempt)

        worker = Worker(
            "worker-test-1",
            client,
            FakeRuntime([blocked]),
            ("assist",),
            heartbeat_enabled=False,
        )
        run_task = asyncio.create_task(worker.run_once())
        await asyncio.sleep(2.5)
        self._run_tick()
        await asyncio.sleep(0.3)
        self.assertEqual(await run_task, "fenced")
        self.assertEqual(submit_calls, 0)
        await client.aclose()
