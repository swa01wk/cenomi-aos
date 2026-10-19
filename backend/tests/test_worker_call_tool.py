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
        decision_id = body["decision"]["decision_id"]
        row = _pg.admin_sql(
            self.db,
            f"select id, event, value from gov.decision_records where id = '{decision_id}';",
        ).stdout.strip()
        self.assertIn(decision_id, row)
        self.assertIn("tool.authorized", row)
        inst = _pg.admin_sql(
            self.db,
            "select run_id, event_type from evidence.execution_events where event_type in ('ToolAuthorized','ToolCompleted') order by aggregate_seq;",
        ).stdout
        self.assertIn("ToolAuthorized", inst)
        self.assertIn("ToolCompleted", inst)

    def test_missing_input_schema_on_grant_is_403_without_connector_call(self) -> None:
        self._start_job()
        attempt_id, fencing = self._claimed()
        _pg.admin_sql(
            self.db,
            f"""
            update work.tasks set contract = jsonb_set(
              contract,
              '{{allowed_tools}}',
              (
                select coalesce(jsonb_agg(
                  case when elem->>'name' = 'browse_categories' then elem - 'input_schema' else elem end
                ), '[]'::jsonb)
                from jsonb_array_elements(contract->'allowed_tools') elem
              ),
              true
            )
            where id = (select task_id from work.attempts where id = '{attempt_id}');
            """,
        )
        r = self._call_tool(attempt_id, "browse_categories", {}, token=fencing)
        self.assertEqual(r.status_code, 403, r.text)
        self.assertEqual(r.json()["code"], "not_permitted")
        self.assertEqual(r.json().get("rule"), "contract.input_schema_missing")
        self.assertEqual(CallToolTests._invoke_calls, 0)
        denied = _pg.admin_sql(
            self.db,
            "select count(*) from evidence.execution_events where event_type = 'ToolDenied';",
        ).stdout.strip()
        self.assertEqual(denied, "1")

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

    def test_connector_timeout_includes_timed_out_flag(self) -> None:
        import asyncio

        self._start_job()
        attempt_id, fencing = self._claimed()

        async def slow_hook(**_kwargs):
            await asyncio.sleep(2.0)

        self.client.app.state.kernel.gateway._timeout_s = 0.05  # type: ignore[attr-defined]
        self.client.app.state.kernel.gateway._invoke_hook = slow_hook  # type: ignore[attr-defined]
        r = self._call_tool(attempt_id, "browse_categories", {}, token=fencing)
        self.assertEqual(r.status_code, 502, r.text)
        body = r.json()
        self.assertEqual(body["code"], "connector_failed")
        self.assertIs(body.get("timed_out"), True)

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
        # Connector tools reach the model with the pack's description, so it knows an empty query lists all.
        browse = next(c for c in ctx.json()["commands"] if c["name"] == "browse_categories")
        self.assertIn("empty query lists them all", browse["description"])
        obs = ctx.json().get("tool_observations") or []
        self.assertGreaterEqual(len(obs), 1)
        self.assertTrue(obs[-1]["untrusted"])
        self.assertIn("items", obs[-1]["content"])

    def test_zero_action_budget_refuses_every_call(self) -> None:
        self._start_job()
        attempt_id, fencing = self._claimed()
        _pg.admin_sql(
            self.db,
            f"""
            update work.tasks set contract = jsonb_set(contract, '{{budget,actions}}', '0'::jsonb, true)
            where id = (select task_id from work.attempts where id = '{attempt_id}');
            """,
        )
        r = self._call_tool(attempt_id, "browse_categories", {}, token=fencing)
        self.assertEqual(r.status_code, 429, r.text)
        self.assertEqual(r.json()["code"], "budget_exhausted")
        self.assertEqual(CallToolTests._invoke_calls, 0)

    def _post_tool_requested(self, attempt_id: str, fencing: int, tool: str):
        r = self.client.post(
            f"/api/worker/attempts/{attempt_id}/events",
            headers={**self.worker_auth(), "X-AOS-Fencing-Token": str(fencing)},
            json={"events": [{"event_type": "ToolRequested", "redacted_summary": f"Tool {tool} requested.",
                              "attributes": {"tool": tool, "args_sha256": "0" * 64}}]},
        )
        self.assertEqual(r.status_code, 202, r.text)

    def _used_actions(self, attempt_id: str) -> int:
        out = _pg.admin_sql(
            self.db, f"select coalesce((usage->>'actions')::int, 0) from work.attempts where id = '{attempt_id}';"
        ).stdout.strip()
        return int(out or 0)

    def test_gateway_call_counts_one_action_with_its_request_event(self) -> None:
        # The worker posts ToolRequested before every tool. A gateway tool is counted when the gateway authorizes
        # it, so its request event must not count again; a kernel tool (save_draft) counts on its request.
        self._start_job()
        attempt_id, fencing = self._claimed()
        _pg.admin_sql(
            self.db,
            f"""
            update work.tasks set contract = jsonb_set(contract, '{{budget,actions}}', '2'::jsonb, true)
            where id = (select task_id from work.attempts where id = '{attempt_id}');
            """,
        )
        for _ in range(2):
            self._post_tool_requested(attempt_id, fencing, "browse_categories")
            r = self._call_tool(attempt_id, "browse_categories", {"query": "janitorial"}, token=fencing)
            self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self._used_actions(attempt_id), 2)
        self._post_tool_requested(attempt_id, fencing, "save_draft")
        self.assertEqual(self._used_actions(attempt_id), 3)

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

    def test_inflight_fence_bump_discards_without_observation_or_payload(self) -> None:
        self._start_job()
        attempt = self._claim()
        attempt_id = attempt["attempt_id"]
        fencing = int(attempt["fencing_token"])
        task_id = attempt["task_id"]
        payloads_before = _pg.admin_sql(
            self.db, "select count(*) from evidence.tool_payloads;"
        ).stdout.strip()

        async def bump_and_call(**_kwargs):
            CallToolTests._invoke_calls += 1
            _pg.admin_sql(
                self.db,
                f"update work.tasks set fencing_token = fencing_token + 1 where id = '{task_id}';",
            )
            async with Client(self.erp_server) as c:
                return await c.call_tool("browse_categories", _kwargs.get("arguments") or {})

        self.client.app.state.kernel.gateway._invoke_hook = bump_and_call  # type: ignore[attr-defined]
        r = self._call_tool(attempt_id, "browse_categories", {}, token=fencing)
        self.assertEqual(r.status_code, 409, r.text)
        self.assertEqual(r.json()["code"], "fenced")
        outcome = _pg.admin_sql(
            self.db,
            "select attributes->>'outcome' from evidence.execution_events where event_type = 'ToolCompleted' order by aggregate_seq desc limit 1;",
        ).stdout.strip()
        self.assertEqual(outcome, "discarded")
        fenced = _pg.admin_sql(
            self.db,
            "select count(*) from evidence.execution_events where event_type = 'AttemptFenced';",
        ).stdout.strip()
        self.assertEqual(fenced, "1")
        obs = _pg.admin_sql(
            self.db,
            f"select tool_observations from work.attempts where id = '{attempt_id}';",
        ).stdout.strip()
        self.assertIn("[]", obs)
        payloads_after = _pg.admin_sql(
            self.db, "select count(*) from evidence.tool_payloads;"
        ).stdout.strip()
        self.assertEqual(payloads_before, payloads_after)


if __name__ == "__main__":
    unittest.main()
