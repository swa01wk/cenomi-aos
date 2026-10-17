"""Mock connectors over real MCP (in-memory transport), with broker tokens and fault switches."""

from __future__ import annotations

import asyncio
import json
import unittest
from pathlib import Path

from mcp.client.client import Client

from aos.connectors import mock_erp, mock_mail
from aos.connectors.base import ConnectorConfig
from aos.connectors.inbound import canonical, verify
from aos.gateway.broker import CredentialBroker, Grant, TokenRejected, verify_token
from aos.registry.loader import parse_yaml

REPO = Path(__file__).resolve().parents[2]
SECRETS = {"mock_erp": "erp-test-secret", "mock_mail": "mail-test-secret"}


def payload(result):
    if result.is_error:
        return {"error": result.content[0].text}
    if not result.content:
        return None
    text = result.content[0].text
    return json.loads(text) if text and text[0] in "[{n\"" else text


def declared_tools(connector: str) -> set[str]:
    doc = parse_yaml((REPO / "packs" / "procurement_demo" / "connectors" / f"{connector}.yaml").read_text())
    return set(doc["spec"]["tools"])


class BrokerTests(unittest.TestCase):
    def test_token_scoped_to_one_action(self) -> None:
        broker = CredentialBroker(SECRETS)
        tok = broker.mint(Grant("mock_erp", "erp_po", "create", "act_1", "org_demo"))
        claims = verify_token(tok, secret=SECRETS["mock_erp"], connector="mock_erp", resource="erp_po", action="create")
        self.assertEqual(claims["sub"], "act_1")
        with self.assertRaises(TokenRejected):
            verify_token(tok, secret=SECRETS["mock_erp"], connector="mock_erp", resource="erp_po", action="read")
        with self.assertRaises(TokenRejected):
            verify_token(tok, secret=SECRETS["mock_mail"], connector="mock_mail", resource="erp_po", action="create")

    def test_expiry_and_rotation(self) -> None:
        now = [1_000_000.0]
        broker = CredentialBroker(SECRETS, ttl_s=60, clock=lambda: now[0])
        tok = broker.mint(Grant("mock_erp", "erp_po", "create", "a", "org"))
        with self.assertRaises(TokenRejected):
            verify_token(tok, secret=SECRETS["mock_erp"], connector="mock_erp", resource="erp_po",
                         action="create", clock=lambda: now[0] + 61)
        broker.rotate({"mock_erp": "rotated-after-kill"})
        with self.assertRaises(TokenRejected):
            verify_token(tok, secret="rotated-after-kill", connector="mock_erp", resource="erp_po", action="create",
                         clock=lambda: now[0])


class MockErpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.broker = CredentialBroker(SECRETS)
        self.cfg = ConnectorConfig(name="mock_erp", secret=SECRETS["mock_erp"])
        self.server, self.store = mock_erp.build_server(self.cfg)

    def tok(self, resource: str, action: str) -> str:
        return self.broker.mint(Grant("mock_erp", resource, action, "act", "org_demo"))

    def po_args(self, key: str = "key-1") -> dict:
        return {"supplier_id": "SUP-10482", "ship_to": "Mall A loading bay", "need_by": "2026-11-20",
                "currency": "SAR", "lines": [{"item": "Cleaning trolley", "quantity": 40, "unit_price": 960}],
                "reference": "AOS-QQ-0001-PO1", "idempotency_key": key, "token": self.tok("erp_po", "create")}

    async def test_server_exposes_every_declared_tool(self) -> None:
        async with Client(self.server) as c:
            names = {t.name for t in (await c.list_tools()).tools}
        declared = declared_tools("mock_erp")
        self.assertLessEqual(declared, names)
        self.assertTrue(all(n.startswith("admin_") for n in names - declared))

    async def test_calls_need_the_right_token(self) -> None:
        async with Client(self.server) as c:
            self.assertIn("error", payload(await c.call_tool("search_suppliers", {"category_id": "CAT-JAN-EQ"})))
            wrong = await c.call_tool("search_suppliers", {"category_id": "CAT-JAN-EQ",
                                                           "token": self.tok("erp_po", "create")})
            self.assertIn("error", payload(wrong))
            ok = payload(await c.call_tool("search_suppliers", {"category_id": "CAT-JAN-EQ",
                                                                "token": self.tok("erp_supplier", "read")}))
            self.assertEqual(len(ok["items"]), 5)

    async def test_history_drives_ranking_signals(self) -> None:
        async with Client(self.server) as c:
            h = payload(await c.call_tool("get_supplier_history", {"supplier_id": "SUP-10482",
                                                                   "token": self.tok("erp_supplier", "read")}))
        self.assertEqual(h["past_pos"], 3)
        self.assertEqual(h["on_time_pct"], 100.0)

    async def test_create_po_is_idempotent(self) -> None:
        async with Client(self.server) as c:
            first = payload(await c.call_tool("create_po", self.po_args()))
            second = payload(await c.call_tool("create_po", self.po_args()))
            pos = payload(await c.call_tool("admin_list_pos", {}))
        self.assertFalse(first["duplicate"])
        self.assertTrue(second["duplicate"])
        self.assertEqual(first["total"], "38400")
        self.assertEqual(len(pos["items"]), 1)

    async def test_timeout_after_commit_is_reconciled_by_reference(self) -> None:
        # Stop 13 of the scenario: the write commits, the reply never arrives, reconciliation finds it.
        async with Client(self.server) as c:
            await c.call_tool("admin_set_faults", {"timeout_after_commit": 1, "timeout_delay_s": 2.0})
            with self.assertRaises(TimeoutError):
                async with asyncio.timeout(0.3):
                    await c.call_tool("create_po", self.po_args())
        async with Client(self.server) as c:
            found = payload(await c.call_tool("find_po", {"reference": "AOS-QQ-0001-PO1",
                                                          "token": self.tok("erp_po", "read")}))
            retry = payload(await c.call_tool("create_po", self.po_args()))
            pos = payload(await c.call_tool("admin_list_pos", {}))
        self.assertTrue(found["found"])
        self.assertEqual(found["po"]["total"], "38400")
        self.assertTrue(retry["duplicate"])
        self.assertEqual(len(pos["items"]), 1, "exactly one PO after timeout and retry")

    async def test_validation_fault_is_reported_not_committed(self) -> None:
        async with Client(self.server) as c:
            await c.call_tool("admin_set_faults", {"fail_validation": 1})
            res = payload(await c.call_tool("create_po", self.po_args()))
            pos = payload(await c.call_tool("admin_list_pos", {}))
        self.assertIn("validation", res["error"])
        self.assertEqual(pos["items"], [])


class MockMailTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.broker = CredentialBroker(SECRETS)
        self.cfg = ConnectorConfig(name="mock_mail", secret=SECRETS["mock_mail"])
        self.server, self.store = mock_mail.build_server(self.cfg, inbound_secret="inbound-test")

    def tok(self, action: str) -> str:
        return self.broker.mint(Grant("mock_mail", "mailbox", action, "act", "org_demo"))

    async def draft(self, c, key="rfq-najd-v2"):
        return payload(await c.call_tool("draft_message", {
            "to": "sales@najd.example", "subject": "Request for quotation: 40 cleaning trolleys (QQ-0001)",
            "body": "Please quote by 21 October.", "conversation_ref": "QQ-0001:SUP-10482",
            "idempotency_key": key, "token": self.tok("draft")}))

    async def test_server_exposes_every_declared_tool(self) -> None:
        async with Client(self.server) as c:
            names = {t.name for t in (await c.list_tools()).tools}
        self.assertLessEqual(declared_tools("mock_mail"), names)

    async def test_send_is_idempotent_and_findable(self) -> None:
        async with Client(self.server) as c:
            d = await self.draft(c)
            args = {"draft_id": d["draft_id"], "idempotency_key": "rfq-najd-v2", "token": self.tok("send")}
            first = payload(await c.call_tool("send_message", args))
            again = payload(await c.call_tool("send_message", args))
            found = payload(await c.call_tool("find_message", {"idempotency_key": "rfq-najd-v2",
                                                               "token": self.tok("read")}))
            sent = payload(await c.call_tool("admin_list", {"folder": "sent"}))
        self.assertFalse(first["duplicate"])
        self.assertTrue(again["duplicate"])
        self.assertEqual(found["message"]["id"], d["draft_id"])
        self.assertEqual(len(sent["items"]), 1)

    async def test_send_needs_send_token_not_draft_token(self) -> None:
        async with Client(self.server) as c:
            d = await self.draft(c)
            res = payload(await c.call_tool("send_message", {"draft_id": d["draft_id"],
                                                             "idempotency_key": "rfq-najd-v2",
                                                             "token": self.tok("draft")}))
        self.assertIn("error", res)

    async def test_reply_raises_a_signed_inbound_event(self) -> None:
        async with Client(self.server) as c:
            d = await self.draft(c)
            await c.call_tool("send_message", {"draft_id": d["draft_id"], "idempotency_key": "rfq-najd-v2",
                                               "token": self.tok("send")})
            note = payload(await c.call_tool("admin_simulate_reply", {
                "conversation_id": d["conversation_id"], "sender": "sales@najd.example",
                "body": "SAR 960 per trolley, 14 days, 12-month warranty."}))
            thread = payload(await c.call_tool("read_thread", {"conversation_id": d["conversation_id"],
                                                               "token": self.tok("read")}))
        self.assertEqual(note["payload"]["event"], "mail.message_received")
        self.assertEqual(note["payload"]["ref"], "QQ-0001:SUP-10482")
        self.assertTrue(verify(canonical(note["payload"]), note["signature"], "inbound-test"))
        self.assertFalse(verify(canonical(note["payload"]), note["signature"], "wrong-secret"))
        self.assertEqual([m["folder"] for m in thread["items"]], ["sent", "inbox"])


if __name__ == "__main__":
    unittest.main()
