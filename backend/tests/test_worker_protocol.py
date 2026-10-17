"""Worker protocol over HTTP + Postgres (M0 scenarios, M1-AG-01 client)."""

from __future__ import annotations

import asyncio
import logging
import time
import unittest

import httpx

from aos.worker.default_fake import minimal_agent_result
from aos.worker.errors import ToolInvocationError
from aos.worker.http_client import HttpKernelClient
from aos.worker.protocol import AttemptFailed
from aos.worker.runner import Worker
from aos.worker.runtime import FakeRuntime
from aos.worker.types import WorkerAttempt

from . import _pg
from .worker_harness import WorkerHarness, make_http_client, mock_erp_hook, settings_with_lease


async def _failing_hook(**_kw):
    raise RuntimeError("connector down")


async def _ok_step(attempt: WorkerAttempt, ctx):
    await ctx.post_events(events=[{"event_type": "AgentStarted", "redacted_summary": "protocol test"}])
    return minimal_agent_result(attempt)


def _record_paths(client: HttpKernelClient) -> list[str]:
    seen: list[str] = []
    real = client._request

    async def wrapped(method, path, **kw):
        seen.append(path.rsplit("/", 1)[-1])
        return await real(method, path, **kw)

    client._request = wrapped  # type: ignore[method-assign]
    return seen


@unittest.skipUnless(_pg.available(), "no local Postgres")
class WorkerProtocolTests(WorkerHarness, unittest.IsolatedAsyncioTestCase):
    async def test_happy_path_submits_once(self) -> None:
        await asyncio.to_thread(self._start_job)
        client = await make_http_client(self, "w1")
        worker = Worker("w1", client, FakeRuntime([_ok_step]), ("assist",))
        self.assertEqual(await asyncio.wait_for(worker.run_once(), 30), "submitted")
        self.assertEqual(await asyncio.wait_for(worker.run_once(), 30), "idle")
        submitted = _pg.admin_sql(
            self.db,
            "select count(*) from work.attempts where outcome = 'submitted';",
        ).stdout.strip()
        self.assertEqual(submitted, "1")
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
        self.assertEqual(await asyncio.wait_for(run_task, 30), "submitted")
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
        while time.monotonic() < claim_mono + lease + 1.0:
            await asyncio.sleep(0.05)
        await asyncio.to_thread(self._run_tick)
        release.set()
        self.assertEqual(await asyncio.wait_for(run_task, 30), "fenced")
        await client.aclose()

    async def test_local_lease_deadline_fences_without_scheduler(self) -> None:
        await asyncio.to_thread(self._start_job)
        client = await make_http_client(self, "w1", settings=settings_with_lease(self, 1.0))

        async def blocked(attempt: WorkerAttempt, ctx):
            await asyncio.Event().wait()

        worker = Worker(
            "w1",
            client,
            FakeRuntime([blocked]),
            ("assist",),
            heartbeat_enabled=False,
        )
        self.assertEqual(await asyncio.wait_for(worker.run_once(), 5), "fenced")
        await client.aclose()

    async def test_stalled_worker_is_fenced_and_cannot_commit(self) -> None:
        await asyncio.to_thread(self._start_job)
        lease = 2.0
        client_a = await make_http_client(self, "A", settings=settings_with_lease(self, lease))
        client_b = await make_http_client(self, "B", settings=settings_with_lease(self, lease))
        gate = asyncio.Event()

        async def stalls(attempt: WorkerAttempt, ctx):
            await gate.wait()
            return minimal_agent_result(attempt)

        worker_a = Worker(
            "A",
            client_a,
            FakeRuntime([stalls]),
            ("assist",),
            heartbeat_enabled=False,
            ignore_local_lease_deadline=True,
        )
        worker_b = Worker("B", client_b, FakeRuntime([_ok_step]), ("assist",))

        task_a = asyncio.create_task(worker_a.run_once())
        await asyncio.sleep(lease + 1.0)
        await asyncio.to_thread(self._run_tick)
        self.assertEqual(await asyncio.wait_for(worker_b.run_once(), 30), "submitted")
        gate.set()
        self.assertEqual(await asyncio.wait_for(task_a, 30), "fenced")
        fenced_events = _pg.admin_sql(
            self.db,
            "select count(*) from evidence.execution_events where event_type = 'AttemptFenced';",
        ).stdout.strip()
        self.assertEqual(fenced_events, "1")
        submitted_by = _pg.admin_sql(
            self.db,
            "select worker_id from work.attempts where outcome = 'submitted';",
        ).stdout.strip()
        self.assertEqual(submitted_by, "B")
        await client_a.aclose()
        await client_b.aclose()

    async def test_expiry_tick_with_margin_fences_and_ends_attempt(self) -> None:
        await asyncio.to_thread(self._start_job)
        lease = 2.0
        client = await make_http_client(self, "w1", settings=settings_with_lease(self, lease))
        release = asyncio.Event()

        async def slow(attempt: WorkerAttempt, ctx):
            await release.wait()
            return minimal_agent_result(attempt)

        worker = Worker("w1", client, FakeRuntime([slow]), ("assist",), heartbeat_enabled=False)
        task = asyncio.create_task(worker.run_once())
        await asyncio.sleep(lease + 1.0)
        await asyncio.to_thread(self._run_tick)
        release.set()
        self.assertEqual(await asyncio.wait_for(task, 30), "fenced")
        ended = _pg.admin_sql(
            self.db,
            "select count(*) from work.attempts where state = 'ENDED' and outcome = 'expired';",
        ).stdout.strip()
        self.assertEqual(ended, "1")
        await client.aclose()

    async def test_fence_bump_on_heartbeat_cancels_runtime(self) -> None:
        await asyncio.to_thread(self._start_job)
        client = await make_http_client(self, "w1", settings=settings_with_lease(self, 3.0))
        paths = _record_paths(client)
        cancelled = asyncio.Event()

        async def blocked(attempt: WorkerAttempt, ctx):
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

        task = asyncio.create_task(
            Worker("w1", client, FakeRuntime([blocked]), ("assist",), heartbeat_enabled=True).run_once()
        )
        await asyncio.sleep(0.5)
        await asyncio.to_thread(
            _pg.admin_sql,
            self.db,
            "update work.tasks set fencing_token = fencing_token + 1;",
        )
        self.assertEqual(await asyncio.wait_for(task, 10), "fenced")
        self.assertTrue(cancelled.is_set())
        self.assertNotIn("submit", paths)
        await client.aclose()

    async def test_failures_are_classified(self) -> None:
        await asyncio.to_thread(self._start_job)

        async def bad(attempt: WorkerAttempt, ctx):
            raise AttemptFailed("invalid_output", "output did not match the brief schema")

        client = await make_http_client(self, "w1")
        worker = Worker("w1", client, FakeRuntime([bad]), ("assist",))
        self.assertEqual(await asyncio.wait_for(worker.run_once(), 30), "failed:invalid_output")
        failure_class = _pg.admin_sql(
            self.db,
            "select failure_class from work.attempts order by admitted_at desc limit 1;",
        ).stdout.strip()
        self.assertEqual(failure_class, "invalid_output")
        await client.aclose()

    async def test_unexpected_errors_are_internal_not_retried(self) -> None:
        await asyncio.to_thread(self._start_job)

        async def boom(attempt: WorkerAttempt, ctx):
            raise RuntimeError("connector exploded")

        client = await make_http_client(self, "w1")
        worker = Worker("w1", client, FakeRuntime([boom]), ("assist",))
        self.assertEqual(await asyncio.wait_for(worker.run_once(), 30), "failed:internal")
        task_id = _pg.admin_sql(self.db, "select id from work.tasks order by created_at desc limit 1;").stdout.strip()
        state = _pg.admin_sql(self.db, f"select state from work.tasks where id = '{task_id}';").stdout.strip()
        self.assertEqual(state, "EXCEPTION")
        admitted = _pg.admin_sql(
            self.db,
            f"select count(*) from work.attempts where task_id = '{task_id}' and state = 'ADMITTED';",
        ).stdout.strip()
        self.assertEqual(admitted, "0")
        await client.aclose()

    async def test_call_tool_e2e_with_connector(self) -> None:
        await asyncio.to_thread(self._start_job)

        async def script(attempt: WorkerAttempt, ctx):
            await ctx.get_contract()
            await ctx.assemble_context(reason="start")
            r = await ctx.call_tool("browse_categories", {"query": "Janitorial"})
            self.assertIn("content", r)
            return minimal_agent_result(attempt)

        client = await make_http_client(self, invoke_hook=mock_erp_hook)
        worker = Worker("worker-test-1", client, FakeRuntime([script]), ("assist",))
        self.assertEqual(await asyncio.wait_for(worker.run_once(), 30), "submitted")
        await client.aclose()

    async def test_connector_failed_maps_to_tool_invocation_error(self) -> None:
        await asyncio.to_thread(self._start_job)
        client = await make_http_client(self, invoke_hook=_failing_hook)
        seen: dict[str, object] = {}

        async def script(attempt: WorkerAttempt, ctx):
            try:
                await ctx.call_tool("browse_categories", {"query": "x"})
            except ToolInvocationError as exc:
                seen["code"] = exc.code
                seen["effect_unknown"] = exc.effect_unknown
            return minimal_agent_result(attempt)

        worker = Worker("worker-test-1", client, FakeRuntime([script]), ("assist",))
        self.assertEqual(await asyncio.wait_for(worker.run_once(), 30), "submitted")
        self.assertEqual(seen.get("code"), "connector_failed")
        self.assertIs(seen.get("effect_unknown"), False)
        await client.aclose()

    async def test_submit_rejected_survives_run_forever(self) -> None:
        await asyncio.to_thread(self._start_job)
        client = await make_http_client(self, "w1")

        async def bad_submit(attempt: WorkerAttempt, ctx):
            r = minimal_agent_result(attempt)
            r["contract_id"] = "not-the-contract"
            return r

        worker = Worker("w1", client, FakeRuntime([bad_submit]), ("assist",), poll_min_s=0.2, poll_max_s=0.5)
        self.assertEqual(await asyncio.wait_for(worker.run_once(), 30), "failed:invalid_output")
        failure_class = _pg.admin_sql(
            self.db,
            "select failure_class from work.attempts order by admitted_at desc limit 1;",
        ).stdout.strip()
        self.assertEqual(failure_class, "invalid_output")
        task = asyncio.create_task(worker.run_forever())
        done, _ = await asyncio.wait({task}, timeout=2.5)
        self.assertFalse(done, "run_forever exited after a rejected submit")
        worker.request_shutdown()
        await asyncio.wait_for(task, 5)
        await client.aclose()

    async def test_auth_failed_exits_run_forever(self) -> None:
        await asyncio.to_thread(self._start_job)
        client = await make_http_client(self, "w1")
        client._token = "not-a-valid-token"
        worker = Worker("w1", client, FakeRuntime([]), ("assist",))
        with self.assertRaises(SystemExit) as ctx:
            await worker.run_forever()
        self.assertEqual(ctx.exception.code, 1)
        await client.aclose()

    async def test_sigterm_cancels_runtime_without_submit(self) -> None:
        await asyncio.to_thread(self._start_job)
        client = await make_http_client(self)
        submit_calls = 0
        real_submit = client.submit_result

        async def counting_submit(attempt, result):
            nonlocal submit_calls
            submit_calls += 1
            return await real_submit(attempt, result)

        client.submit_result = counting_submit  # type: ignore[method-assign]
        cancelled = asyncio.Event()

        async def blocked(attempt: WorkerAttempt, ctx):
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

        worker = Worker("worker-test-1", client, FakeRuntime([blocked]), ("assist",))
        task = asyncio.create_task(worker.run_forever())
        await asyncio.sleep(0.5)
        t0 = time.monotonic()
        worker.request_shutdown()
        await asyncio.wait_for(task, 3)
        self.assertLess(time.monotonic() - t0, 1.0)
        self.assertTrue(cancelled.is_set())
        self.assertEqual(submit_calls, 0)
        await client.aclose()


class WorkerResilienceTests(unittest.IsolatedAsyncioTestCase):
    async def test_kernel_unreachable_on_claim_keeps_polling(self) -> None:
        def boom(request):
            raise httpx.ConnectError("kernel down")

        raw = httpx.AsyncClient(transport=httpx.MockTransport(boom), base_url="http://x/api")
        client = HttpKernelClient("http://x/api", "t", client=raw)
        worker = Worker("w", client, FakeRuntime([]), ("assist",), poll_min_s=0.2, poll_max_s=0.5)
        task = asyncio.create_task(worker.run_forever())
        done, _ = await asyncio.wait({task}, timeout=2.5)
        self.assertFalse(done, "run_forever exited while kernel was unreachable")
        worker.request_shutdown()
        await asyncio.wait_for(task, 5)
        await client.aclose()

    async def test_kernel_problem_on_claim_keeps_polling(self) -> None:
        def forbidden(request):
            return httpx.Response(
                403,
                json={
                    "type": "about:blank",
                    "code": "not_permitted",
                    "title": "Not permitted",
                    "detail": "claim denied for test",
                },
            )

        raw = httpx.AsyncClient(transport=httpx.MockTransport(forbidden), base_url="http://x/api")
        client = HttpKernelClient("http://x/api", "t", client=raw)
        worker = Worker("w", client, FakeRuntime([]), ("assist",), poll_min_s=0.2, poll_max_s=0.5)
        task = asyncio.create_task(worker.run_forever())
        done, _ = await asyncio.wait({task}, timeout=2.5)
        self.assertFalse(done, "run_forever exited after a non-401 claim problem")
        worker.request_shutdown()
        await asyncio.wait_for(task, 5)
        await client.aclose()


class FakeModelTests(unittest.TestCase):
    def test_scripted_turns_in_order(self) -> None:
        from aos.worker.fake_model import FakeModel, ScriptedTurn

        m = FakeModel([ScriptedTurn(tool_calls=[{"name": "search_suppliers"}]), ScriptedTurn(text="done")])
        self.assertEqual(m.invoke(["hi"]).tool_calls[0]["name"], "search_suppliers")
        self.assertEqual(m.invoke(["next"]).text, "done")
        with self.assertRaises(RuntimeError):
            m.invoke(["more"])
