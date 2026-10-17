"""M1-BE-07: callTool gateway reads."""

from __future__ import annotations

import asyncio
import concurrent.futures
import unittest

from mcp.client.client import Client

from aos.connectors import mock_erp
from aos.connectors.base import ConnectorConfig
from aos.gateway.broker import CredentialBroker, Grant

from . import _pg
from .test_worker_api import WORKFLOW, WorkerHarness

SECRETS = {"mock_erp": "erp-test-secret", "mock_mail": "mail-test-secret"}


def _event_types(db, instance_id: str) -> list[str]:
    out = _pg.admin_sql(
        db,
        f"select event_type from evidence.execution_events where run_id = '{instance_id}' order by aggregate_seq;",
    ).stdout.strip()
    return [line for line in out.splitlines() if line]


@unittest.skipUnless(_pg.available(), "no local Postgres")
class CallToolTests(WorkerHarness):
    erp_server = None
    erp_cfg: ConnectorConfig | None = None
    _invoke_calls = 0

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.erp_cfg = ConnectorConfig(name="mock_erp", secret=SECRETS["mock_erp"])
        cls.erp_server, _ = mock_erp.build_server(cls.erp_cfg)

    @classmethod
    async def _erp_hook(cls, *, connector: str, tool: str, arguments: dict):
        CallToolTests._invoke_calls += 1
        if connector != "mock_erp":
            raise KeyError(connector)
        async with Client(cls.erp_server) as c:
            return await c.call_tool(tool, arguments)

    def _wire_gateway(self) -> None:
        kernel = self.client.app.state.kernel
        kernel.gateway._invoke_hook = self._erp_hook  # type: ignore[attr-defined]
        kernel.broker = CredentialBroker(SECRETS)

    def setUp(self) -> None:
        super().setUp()
        CallToolTests._invoke_calls = 0
        self._wire_gateway()

    def _call_tool(self, attempt_id: str, tool: str, args: dict | None = None, token: int | None = None):
        headers = self.worker_auth()
        if token is not None:
            headers["X-AOS-Fencing-Token"] = str(token)
        return self.client.post(
            f"/api/worker/attempts/{attempt_id}/tools/{tool}",
            headers=headers,
            json={"args": args or {}},
        )

    def _claimed(self) -> tuple[str, int]:
        attempt = self._claim()
        return attempt["attempt_id"], int(attempt["fencing_token"])

    def test_tool_outside_contract_is_403_without_connector_call(self) -> None:
        self._start_job()
        attempt_id, fencing = self._claimed()
        r = self._call_tool(attempt_id, "search_suppliers", {"category_id": "CAT-JAN-EQ"}, token=fencing)
        self.assertEqual(r.status_code, 403, r.text)
        self.assertEqual(r.json()["code"], "not_permitted")
        self.assertEqual(CallToolTests._invoke_calls, 0)
        denied = _pg.admin_sql(
            self.db,
            "select count(*) from evidence.execution_events where event_type = 'ToolDenied';",
        ).stdout.strip()
        self.assertEqual(denied, "1")

    def test_browse_categories_allow_path(self) -> None:
        self._start_job()
        attempt_id, fencing = self._claimed()
        r = self._call_tool(attempt_id, "browse_categories", {"query": "Janitorial"}, token=fencing)
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertTrue(body["untrusted"])
        self.assertIn("items", body["content"])
        inst = _pg.admin_sql(
            self.db,
            "select run_id, event_type from evidence.execution_events where event_type in ('ToolAuthorized','ToolCompleted') order by aggregate_seq;",
        ).stdout
        self.assertIn("ToolAuthorized", inst)
        self.assertIn("ToolCompleted", inst)

    def test_invalid_input_is_422_without_connector_call(self) -> None:
        self._start_job()
        attempt_id, fencing = self._claimed()
        r = self._call_tool(attempt_id, "browse_categories", {"query": 12}, token=fencing)
        self.assertEqual(r.status_code, 422, r.text)
        self.assertEqual(CallToolTests._invoke_calls, 0)

    def test_fenced_call_tool_returns_409(self) -> None:
        self._start_job()
        attempt_id, _ = self._claimed()
        r = self._call_tool(attempt_id, "browse_categories", {}, token=0)
        self.assertEqual(r.status_code, 409, r.text)
        self.assertEqual(r.json()["code"], "fenced")

    def test_connector_failure_returns_502_with_outcome_failed(self) -> None:
        self._start_job()
        attempt_id, fencing = self._claimed()

        async def fail_hook(**_kwargs):
            CallToolTests._invoke_calls += 1
            raise RuntimeError("connector down")

        self.client.app.state.kernel.gateway._invoke_hook = fail_hook  # type: ignore[attr-defined]
        r = self._call_tool(attempt_id, "browse_categories", {}, token=fencing)
        self.assertEqual(r.status_code, 502, r.text)
        self.assertEqual(r.json()["code"], "connector_failed")
        out = _pg.admin_sql(
            self.db,
            "select attributes->>'outcome' from evidence.execution_events where event_type = 'ToolCompleted' order by aggregate_seq desc limit 1;",
        ).stdout.strip()
        self.assertEqual(out, "failed")

    def test_context_includes_untrusted_observation(self) -> None:
        self._start_job()
        attempt_id, fencing = self._claimed()
        tr = self._call_tool(attempt_id, "browse_categories", {"query": "Janitorial"}, token=fencing)
        self.assertEqual(tr.status_code, 200, tr.text)
        ctx = self.client.post(
            f"/api/worker/attempts/{attempt_id}/context",
            headers={**self.worker_auth(), "X-AOS-Fencing-Token": str(fencing)},
            json={"reason": "tool_result"},
        )
        self.assertEqual(ctx.status_code, 200, ctx.text)
        obs = ctx.json().get("tool_observations") or []
        self.assertGreaterEqual(len(obs), 1)
        self.assertTrue(obs[-1]["untrusted"])
        self.assertIn("items", obs[-1]["content"])

    def test_concurrent_calls_with_one_action_budget(self) -> None:
        self._start_job()
        attempt_id, fencing = self._claimed()
        _pg.admin_sql(
            self.db,
            f"""
            update work.tasks set contract = jsonb_set(contract, '{{budget,actions}}', '1'::jsonb, true)
            where id = (select task_id from work.attempts where id = '{attempt_id}');
            """,
        )

        def one_call():
            return self._call_tool(attempt_id, "browse_categories", {}, token=fencing)

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            a, b = list(pool.map(lambda _: one_call(), range(2)))
        codes = sorted([a.status_code, b.status_code])
        self.assertEqual(codes, [200, 429])
        auth_count = _pg.admin_sql(
            self.db,
            "select count(*) from evidence.execution_events where event_type = 'ToolAuthorized';",
        ).stdout.strip()
        self.assertEqual(auth_count, "1")

    def test_broker_token_expiry_on_connector(self) -> None:
        now = [1_000_000.0]
        broker = CredentialBroker(SECRETS, ttl_s=60, clock=lambda: now[0])
        tok = broker.mint(
            Grant("mock_erp", "erp_supplier", "read", "act", "org_demo", "browse_categories", "att_x")
        )
        cfg = ConnectorConfig(name="mock_erp", secret=SECRETS["mock_erp"], clock=lambda: now[0])
        server, _ = mock_erp.build_server(cfg)

        async def run_at(offset: float):
            now[0] = 1_000_000.0 + offset
            async with Client(server) as c:
                return await c.call_tool("browse_categories", {"token": tok})

        async def main():
            ok = await run_at(59)
            self.assertFalse(ok.is_error)
            late = await run_at(61)
            self.assertTrue(late.is_error)

        asyncio.run(main())


if __name__ == "__main__":
    unittest.main()
