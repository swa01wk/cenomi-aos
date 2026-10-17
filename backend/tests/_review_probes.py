"""Review probes for M1-AG-01: each prints what the worker actually does in one scenario.

Not part of `make check` (no `test_` prefix, so discovery skips it). Run from backend/:
    PYTHONPATH=src:.vendor python3 -m unittest tests._review_probes -v
Delete once the scenarios are covered by real tests in test_worker_protocol / test_worker_runtime.
"""

from __future__ import annotations

import asyncio
import time
import unittest

import httpx
from mcp.client.client import Client

from aos.connectors import mock_erp
from aos.connectors.base import ConnectorConfig
from aos.gateway.broker import CredentialBroker
from aos.worker.default_fake import minimal_agent_result
from aos.worker.errors import ToolInvocationError
from aos.worker.http_client import HttpKernelClient
from aos.worker.runner import Worker
from aos.worker.runtime import FakeRuntime, LangGraphRuntime

from . import _pg
from .worker_harness import WorkerHarness, make_http_client, settings_with_lease

SECRETS = {"mock_erp": "erp-test-secret", "mock_mail": "mail-test-secret"}
ERP = mock_erp.build_server(ConnectorConfig(name="mock_erp", secret=SECRETS["mock_erp"]))[0]


async def erp_hook(*, connector, tool, arguments):
    async with Client(ERP) as c:
        return await c.call_tool(tool, arguments)


async def failing_hook(**_kw):
    raise RuntimeError("connector down")


def record_paths(client: HttpKernelClient) -> list[str]:
    seen: list[str] = []
    real = client._request

    async def wrapped(method, path, **kw):
        seen.append(path.rsplit("/", 1)[-1])
        return await real(method, path, **kw)

    client._request = wrapped  # type: ignore[method-assign]
    return seen


def q(db, sql):
    return _pg.admin_sql(db, sql).stdout.strip()


class Probes(WorkerHarness, unittest.IsolatedAsyncioTestCase):
    async def _client(self, worker_id="worker-test-1", lease=None, hook=erp_hook):
        s = settings_with_lease(self, lease) if lease else None
        c = await make_http_client(self, worker_id, settings=s, invoke_hook=hook)
        return c

    async def asyncSetUp(self):
        await asyncio.to_thread(self._start_job)

    def _broker(self, client):
        pass

    async def test_p1_call_tool_e2e_with_connector(self):
        c = await self._client()
        c._client._transport.app.state.kernel.broker = CredentialBroker(SECRETS)  # type: ignore[union-attr]

        async def script(attempt, ctx):
            await ctx.get_contract()
            await ctx.assemble_context(reason="start")
            r = await ctx.call_tool("browse_categories", {"query": "Janitorial"})
            print("\n[P1] tool content:", str(r.get("content"))[:80])
            return minimal_agent_result(attempt)

        print("[P1] outcome:", await Worker("worker-test-1", c, FakeRuntime([script]), ("assist",)).run_once())

    async def test_p2_connector_failed_mapping(self):
        c = await self._client(hook=failing_hook)
        c._client._transport.app.state.kernel.broker = CredentialBroker(SECRETS)  # type: ignore[union-attr]
        got = {}

        async def script(attempt, ctx):
            try:
                await ctx.call_tool("browse_categories", {"query": "x"})
            except ToolInvocationError as e:
                got.update(code=e.code, effect_unknown=e.effect_unknown)
            return minimal_agent_result(attempt)

        out = await Worker("worker-test-1", c, FakeRuntime([script]), ("assist",)).run_once()
        print("\n[P2] 502 connector_failed seen by runtime as:", got, "| outcome:", out)

    async def test_p3_fence_bump_heartbeat_cancels_runtime(self):
        c = await self._client(lease=3.0)
        paths = record_paths(c)
        cancelled = asyncio.Event()

        async def blocked(attempt, ctx):
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

        task = asyncio.create_task(Worker("worker-test-1", c, FakeRuntime([blocked]), ("assist",)).run_once())
        await asyncio.sleep(0.5)
        await asyncio.to_thread(q, self.db, "update work.tasks set fencing_token = fencing_token + 1;")
        try:
            out = await asyncio.wait_for(task, 5)
        except Exception as e:  # noqa: BLE001
            out = f"RAISED {type(e).__name__}: {e}"
        print("\n[P3] outcome:", out, "| runtime cancelled:", cancelled.is_set(), "| calls:", paths)

    async def test_p4_stalled_worker_kernel_rejects_stale_submit(self):
        ca = await self._client("A", lease=2.0)
        cb = await self._client("B", lease=2.0)
        gate = asyncio.Event()

        async def stalls(attempt, ctx):
            await gate.wait()
            return minimal_agent_result(attempt)

        async def ok(attempt, ctx):
            return minimal_agent_result(attempt)

        ta = asyncio.create_task(Worker("A", ca, FakeRuntime([stalls]), ("assist",), heartbeat_enabled=False).run_once())
        await asyncio.sleep(3.0)
        await asyncio.to_thread(self._run_tick)
        b = await Worker("B", cb, FakeRuntime([ok]), ("assist",)).run_once()
        gate.set()
        try:
            a = await asyncio.wait_for(ta, 5)
        except Exception as e:  # noqa: BLE001
            a = f"RAISED {type(e).__name__}"
        fenced_events = q(self.db, "select count(*) from evidence.execution_events where event_type='AttemptFenced';")
        submitted = q(self.db, "select worker_id from work.attempts where outcome='submitted';")
        print(f"\n[P4] B={b} A={a} | AttemptFenced events={fenced_events} | submitted by={submitted!r}")

    async def test_p5_negative_control_with_margin(self):
        c = await self._client(lease=2.0)
        paths = record_paths(c)
        rel = asyncio.Event()

        async def slow(attempt, ctx):
            await rel.wait()
            return minimal_agent_result(attempt)

        task = asyncio.create_task(
            Worker("worker-test-1", c, FakeRuntime([slow]), ("assist",), heartbeat_enabled=False).run_once()
        )
        await asyncio.sleep(3.0)
        await asyncio.to_thread(self._run_tick)
        rel.set()
        try:
            out = await asyncio.wait_for(task, 5)
        except Exception as e:  # noqa: BLE001
            out = f"RAISED {type(e).__name__}"
        print("\n[P5] outcome:", out, "| calls:", paths)

    async def test_p6_runtime_blocked_no_heartbeat_hangs(self):
        c = await self._client(lease=1.0)

        async def blocked(attempt, ctx):
            await asyncio.Event().wait()

        task = asyncio.create_task(
            Worker("worker-test-1", c, FakeRuntime([blocked]), ("assist",), heartbeat_enabled=False).run_once()
        )
        try:
            out = await asyncio.wait_for(task, 4)
        except asyncio.TimeoutError:
            out = "STILL RUNNING 3s after local lease deadline"
        print("\n[P6]", out)

    async def test_p7_sigterm_during_attempt(self):
        c = await self._client()
        w = Worker("worker-test-1", c, FakeRuntime([lambda a, ctx: asyncio.Event().wait()]), ("assist",))
        task = asyncio.create_task(w.run_forever())
        await asyncio.sleep(0.5)
        w.request_shutdown()
        t0 = time.monotonic()
        try:
            await asyncio.wait_for(task, 3)
            out = f"stopped after {time.monotonic() - t0:.1f}s"
        except asyncio.TimeoutError:
            out = "NOT stopped 3s after shutdown request (runtime not cancelled)"
        print("\n[P7] SIGTERM:", out)

    async def test_p9_langgraph_runtime_kills_tasks(self):
        c = await self._client()
        out = await Worker("worker-test-1", c, LangGraphRuntime(), ("assist",)).run_once()
        state = q(self.db, "select state from work.tasks order by created_at desc limit 1;")
        print("\n[P9] AOS_RUNTIME=langgraph claims and ends attempt:", out, "| task state:", state)

    async def test_p11_submit_rejected_non_fenced(self):
        c = await self._client()

        async def bad(attempt, ctx):
            r = minimal_agent_result(attempt)
            r["contract_id"] = "nope"
            return r

        try:
            out = await Worker("worker-test-1", c, FakeRuntime([bad]), ("assist",)).run_once()
        except Exception as e:  # noqa: BLE001
            out = f"RAISED {type(e).__name__}: {e}"
        print("\n[P11] submit rejected by kernel ->", out)


class NoPgProbes(unittest.IsolatedAsyncioTestCase):
    async def test_p8_kernel_down_on_claim(self):
        def boom(request):
            raise httpx.ConnectError("kernel down")

        raw = httpx.AsyncClient(transport=httpx.MockTransport(boom), base_url="http://x/api")
        c = HttpKernelClient("http://x/api", "t", client=raw)
        w = Worker("w", c, FakeRuntime([]), ("assist",))
        try:
            await asyncio.wait_for(w.run_forever(), 3)
            out = "kept running"
        except asyncio.TimeoutError:
            out = "kept polling (good)"
        except Exception as e:  # noqa: BLE001
            out = f"run_forever CRASHED with {type(e).__name__}"
        print("\n[P8] kernel unreachable during claim:", out)
