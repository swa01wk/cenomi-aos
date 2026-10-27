"""Mock connectors over real MCP (in-memory transport), with broker tokens and fault switches."""

from __future__ import annotations

import asyncio
import json
import unittest
from pathlib import Path

from mcp.client.client import Client

from aos.connectors import mock_erp, mock_erp_seed, mock_mail
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
        tok = broker.mint(
            Grant("mock_erp", "erp_po", "create", "act_1", "org_demo", "create_po", "att_1")
        )
        claims = verify_token(
            tok,
            secret=SECRETS["mock_erp"],
            connector="mock_erp",
            resource="erp_po",
            action="create",
            tool="create_po",
        )
        self.assertEqual(claims["sub"], "act_1")
        with self.assertRaises(TokenRejected):
            verify_token(tok, secret=SECRETS["mock_erp"], connector="mock_erp", resource="erp_po", action="read")
        with self.assertRaises(TokenRejected):
            verify_token(tok, secret=SECRETS["mock_mail"], connector="mock_mail", resource="erp_po", action="create")

    def test_expiry_and_rotation(self) -> None:
        now = [1_000_000.0]
        broker = CredentialBroker(SECRETS, ttl_s=60, clock=lambda: now[0])
        tok = broker.mint(Grant("mock_erp", "erp_po", "create", "a", "org", "create_po", "att_1"))
        verify_token(
            tok,
            secret=SECRETS["mock_erp"],
            connector="mock_erp",
            resource="erp_po",
            action="create",
            tool="create_po",
            clock=lambda: now[0] + 59,
        )
        with self.assertRaises(TokenRejected):
            verify_token(
                tok,
                secret=SECRETS["mock_erp"],
                connector="mock_erp",
                resource="erp_po",
                action="create",
                tool="create_po",
                clock=lambda: now[0] + 61,
            )
        broker.rotate({"mock_erp": "rotated-after-kill"})
        with self.assertRaises(TokenRejected):
            verify_token(tok, secret="rotated-after-kill", connector="mock_erp", resource="erp_po", action="create",
                         clock=lambda: now[0])


class MockErpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.broker = CredentialBroker(SECRETS)
        self.cfg = ConnectorConfig(name="mock_erp", secret=SECRETS["mock_erp"])
        self.server, self.store = mock_erp.build_server(self.cfg)

    def tok(self, resource: str, action: str, tool: str) -> str:
        return self.broker.mint(
            Grant("mock_erp", resource, action, "act", "org_demo", tool, "att_test")
        )

    def po_args(self, key: str = "key-1") -> dict:
        return {"supplier_id": "SUP-10482", "ship_to": "Mall A loading bay", "need_by": "2026-11-20",
                "currency": "SAR", "lines": [{"item": "Cleaning trolley", "quantity": 40, "unit_price": 960}],
                "reference": "AOS-QQ-0001-PO1", "idempotency_key": key, "token": self.tok("erp_po", "create", "create_po")}

    async def test_server_exposes_every_declared_tool(self) -> None:
        async with Client(self.server) as c:
            names = {t.name for t in (await c.list_tools()).tools}
        declared = declared_tools("mock_erp")
        self.assertLessEqual(declared, names)
        self.assertTrue(all(n.startswith("admin_") for n in names - declared))

    async def test_token_tool_name_must_match(self) -> None:
        async with Client(self.server) as c:
            tok = self.tok("erp_supplier", "read", "browse_categories")
            res = payload(
                await c.call_tool(
                    "search_suppliers",
                    {"category_id": "CAT-JAN-EQ", "token": tok},
                )
            )
            self.assertIn("error", res)

    async def test_calls_need_the_right_token(self) -> None:
        async with Client(self.server) as c:
            self.assertIn("error", payload(await c.call_tool("search_suppliers", {"category_id": "CAT-JAN-EQ"})))
            wrong = await c.call_tool("search_suppliers", {"category_id": "CAT-JAN-EQ",
                                                           "token": self.tok("erp_po", "create", "create_po")})
            self.assertIn("error", payload(wrong))
            wrong_tool = await c.call_tool(
                "search_suppliers",
                {
                    "category_id": "CAT-JAN-EQ",
                    "token": self.tok("erp_supplier", "read", "browse_categories"),
                },
            )
            self.assertIn("error", payload(wrong_tool))
            ok = payload(await c.call_tool("search_suppliers", {"category_id": "CAT-JAN-EQ",
                                                                "token": self.tok("erp_supplier", "read", "search_suppliers")}))
            self.assertEqual(len(ok["items"]), 5)

    async def test_history_drives_ranking_signals(self) -> None:
        async with Client(self.server) as c:
            h = payload(await c.call_tool("get_supplier_history", {"supplier_id": "SUP-10482",
                                                                   "token": self.tok("erp_supplier", "read", "get_supplier_history")}))
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
                                                          "token": self.tok("erp_po", "read", "find_po")}))
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

    async def browse(self, c: Client, query: str) -> list[str]:
        res = payload(await c.call_tool("browse_categories", {
            "query": query, "token": self.tok("erp_supplier", "read", "browse_categories")}))
        return [item["id"] for item in res["items"]]

    async def suppliers(self, c: Client, category_id: str) -> list[dict]:
        res = payload(await c.call_tool("search_suppliers", {
            "category_id": category_id, "token": self.tok("erp_supplier", "read", "search_suppliers")}))
        return res["items"]

    async def test_browse_matches_items_and_plurals(self) -> None:
        async with Client(self.server) as c:
            self.assertEqual(await self.browse(c, "cleaning trolley"), ["CAT-JAN-EQ"])
            self.assertIn("CAT-IT-EUD", await self.browse(c, "macbooks"))
            self.assertEqual(await self.browse(c, "MacBook Pro"), ["CAT-IT-EUD"])
            self.assertEqual(await self.browse(c, "sweepers"), ["CAT-FLR-MCH"])
            self.assertIn("CAT-IT-MON", await self.browse(c, "27-inch monitors"))
            self.assertEqual(await self.browse(c, "xyzzy"), [])
            self.assertGreaterEqual(len(await self.browse(c, "")), 30)

    async def test_demo_suppliers_and_history_stay_fixed(self) -> None:
        async with Client(self.server) as c:
            jan = await self.suppliers(c, "CAT-JAN-EQ")
            self.assertEqual([s["id"] for s in jan], ["SUP-10217", "SUP-10355", "SUP-10482", "SUP-10611", "SUP-10790"])
            self.assertEqual(jan[2], {"id": "SUP-10482", "name": "Najd Supplies", "email": "sales@najd.example",
                                      "category_id": "CAT-JAN-EQ"})
            tok = self.tok("erp_supplier", "read", "get_supplier_history")
            desert = payload(await c.call_tool("get_supplier_history", {"supplier_id": "SUP-10355", "token": tok}))
            gulf = payload(await c.call_tool("get_supplier_history", {"supplier_id": "SUP-10790", "token": tok}))
        self.assertEqual([(o["po_number"], o["on_time"]) for o in desert["orders"]],
                         [("PO-771950", 1), ("PO-773012", 0)])
        self.assertEqual(desert["on_time_pct"], 50.0)
        self.assertEqual({o["category_id"] for o in desert["orders"]}, {"CAT-JAN-EQ"})
        self.assertEqual((gulf["past_pos"], gulf["on_time_pct"]), (0, None))

    async def test_it_service_vendor_has_full_master_data(self) -> None:
        async with Client(self.server) as c:
            managed = await self.suppliers(c, "CAT-IT-MSV")
            laptops = await self.suppliers(c, "CAT-IT-EUD")
        rawabi = next(s for s in managed if s["name"] == "Rawabi Digital Services")
        self.assertEqual(rawabi["email"], "rfq@rawabi-digital.example")
        self.assertIn(rawabi["id"], {s["id"] for s in laptops})
        self.assertNotIn("Old Town Computers", {s["name"] for s in laptops}, "a suspended supplier is never offered")
        vendor = self.store.one("select VENDOR_ID from POZ_SUPPLIERS where SEGMENT1 = ?", (rawabi["id"],))["VENDOR_ID"]
        sites = self.store.q("select VENDOR_SITE_CODE from POZ_SUPPLIER_SITES_ALL_M where VENDOR_ID = ?", (vendor,))
        contacts = self.store.q("select JOB_TITLE from POZ_SUPPLIER_CONTACTS where VENDOR_ID = ?", (vendor,))
        agreement = self.store.one("select SEGMENT1 from PO_HEADERS_ALL where VENDOR_ID = ? and"
                                   " TYPE_LOOKUP_CODE = 'BLANKET'", (vendor,))
        self.assertEqual({s["VENDOR_SITE_CODE"] for s in sites}, {"RUH-HQ", "JED-BR", "DMM-BR"})
        self.assertIn("Key Account Manager", {c["JOB_TITLE"] for c in contacts})
        self.assertEqual(agreement["SEGMENT1"], "BPA-2025-0014")

    async def test_created_po_lands_in_fusion_tables(self) -> None:
        async with Client(self.server) as c:
            po = payload(await c.call_tool("create_po", self.po_args()))
        self.assertEqual(po["id"], "PO-778201")
        self.assertEqual(po["lines"], [{"item": "Cleaning trolley", "quantity": 40, "unit_price": 960}])
        self.assertEqual((po["ship_to"], po["need_by"], po["supplier_id"]),
                         ("Mall A loading bay", "2026-11-20", "SUP-10482"))
        header = self.store.one("select * from PO_HEADERS_ALL where ATTRIBUTE1 = 'AOS-QQ-0001-PO1'")
        location = self.store.one("select l.LOCATION_CODE from PO_LINE_LOCATIONS_ALL ll join HR_LOCATIONS_ALL l"
                                  " on l.LOCATION_ID = ll.SHIP_TO_LOCATION_ID where ll.PO_HEADER_ID = ?",
                                  (header["PO_HEADER_ID"],))
        self.assertEqual((header["TYPE_LOOKUP_CODE"], header["DOCUMENT_STATUS"]), ("STANDARD", "OPEN"))
        self.assertEqual(location["LOCATION_CODE"], "MALLA-LB")

    def test_seed_is_large_and_runs_once(self) -> None:
        counts = {t: self.store.one(f"select count(*) as n from {t}")["n"]
                  for t in ("EGP_CATEGORIES_B", "EGP_SYSTEM_ITEMS_B", "POZ_SUPPLIERS", "PO_HEADERS_ALL")}
        self.assertGreaterEqual(counts["EGP_CATEGORIES_B"], 30)
        self.assertGreaterEqual(counts["EGP_SYSTEM_ITEMS_B"], 180)
        self.assertGreaterEqual(counts["POZ_SUPPLIERS"], 80)
        self.assertGreaterEqual(counts["PO_HEADERS_ALL"], 200)
        mock_erp_seed.seed(self.store)
        self.assertEqual(self.store.one("select count(*) as n from POZ_SUPPLIERS")["n"], counts["POZ_SUPPLIERS"])


class MockMailTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        # Host .env often carries real SMTP credentials; connector tests must never send live mail.
        from unittest.mock import patch

        self._relay_patcher = patch("aos.connectors.mock_mail._relay_via_smtp")
        self._relay_patcher.start()

    def tearDown(self) -> None:
        self._relay_patcher.stop()

    async def asyncSetUp(self) -> None:
        self.broker = CredentialBroker(SECRETS)
        self.cfg = ConnectorConfig(name="mock_mail", secret=SECRETS["mock_mail"])
        self.server, self.store = mock_mail.build_server(self.cfg, inbound_secret="inbound-test")

    def tok(self, action: str, tool: str) -> str:
        return self.broker.mint(Grant("mock_mail", "mailbox", action, "act", "org_demo", tool, "att_test"))

    async def draft(self, c, key="rfq-najd-v2"):
        return payload(await c.call_tool("draft_message", {
            "to": "sales@najd.example", "subject": "Request for quotation: 40 cleaning trolleys (QQ-0001)",
            "body": "Please quote by 21 October.", "conversation_ref": "QQ-0001:SUP-10482",
            "idempotency_key": key, "token": self.tok("draft", "draft_message")}))

    async def test_server_exposes_every_declared_tool(self) -> None:
        async with Client(self.server) as c:
            names = {t.name for t in (await c.list_tools()).tools}
        self.assertLessEqual(declared_tools("mock_mail"), names)

    async def test_send_relays_when_smtp_configured(self) -> None:
        from unittest.mock import patch

        async with Client(self.server) as c:
            d = await self.draft(c, key="rfq-smtp-relay")
            args = {
                "draft_id": d["draft_id"],
                "idempotency_key": "rfq-smtp-relay",
                "token": self.tok("send", "send_message"),
            }
            with patch("aos.connectors.mock_mail._relay_via_smtp") as relay:
                payload(await c.call_tool("send_message", args))
                relay.assert_called_once()
                kw = relay.call_args.kwargs
                self.assertEqual(kw["to"], "sales@najd.example")
                self.assertIn("quotation", kw["subject"].lower())

    async def test_send_is_idempotent_and_findable(self) -> None:
        async with Client(self.server) as c:
            d = await self.draft(c)
            args = {"draft_id": d["draft_id"], "idempotency_key": "rfq-najd-v2", "token": self.tok("send", "send_message")}
            first = payload(await c.call_tool("send_message", args))
            again = payload(await c.call_tool("send_message", args))
            found = payload(await c.call_tool("find_message", {"idempotency_key": "rfq-najd-v2",
                                                               "token": self.tok("read", "find_message")}))
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
                                                             "token": self.tok("draft", "draft_message")}))
        self.assertIn("error", res)

    async def test_reply_raises_a_signed_inbound_event(self) -> None:
        async with Client(self.server) as c:
            d = await self.draft(c)
            await c.call_tool("send_message", {"draft_id": d["draft_id"], "idempotency_key": "rfq-najd-v2",
                                               "token": self.tok("send", "send_message")})
            note = payload(await c.call_tool("admin_simulate_reply", {
                "conversation_id": d["conversation_id"], "sender": "sales@najd.example",
                "body": "SAR 960 per trolley, 14 days, 12-month warranty."}))
            thread = payload(await c.call_tool("read_thread", {"conversation_id": d["conversation_id"],
                                                               "token": self.tok("read", "read_thread")}))
        self.assertEqual(note["payload"]["event"], "mail.message_received")
        self.assertEqual(note["payload"]["ref"], "QQ-0001:SUP-10482")
        self.assertTrue(verify(canonical(note["payload"]), note["signature"], "inbound-test"))
        self.assertFalse(verify(canonical(note["payload"]), note["signature"], "wrong-secret"))
        self.assertEqual([m["folder"] for m in thread["items"]], ["sent", "inbox"])


def _worker_args_schema(schema: dict) -> dict:
    props = {
        k: {"type": v.get("type")}
        for k, v in (schema.get("properties") or {}).items()
        if k != "token" and isinstance(v, dict) and v.get("type")
    }
    required = [r for r in schema.get("required") or [] if r != "token"]
    out: dict = {"type": "object", "properties": props}
    if required:
        out["required"] = required
    return out


class PackInputSchemaTests(unittest.IsolatedAsyncioTestCase):
    async def test_mcp_read_tools_match_mock_server_schemas(self) -> None:
        for connector in ("mock_erp", "mock_mail"):
            doc = parse_yaml(
                (REPO / "packs" / "procurement_demo" / "connectors" / f"{connector}.yaml").read_text()
            )
            cfg = ConnectorConfig(name=connector, secret=SECRETS[connector])
            if connector == "mock_erp":
                server, _ = mock_erp.build_server(cfg)
            else:
                server, _ = mock_mail.build_server(cfg, inbound_secret="inbound-test")
            async with Client(server) as c:
                listed = {t.name: t for t in (await c.list_tools()).tools}
            for tname, spec in doc["spec"]["tools"].items():
                if spec.get("class") != "read":
                    continue
                declared = spec.get("input_schema")
                self.assertIsInstance(declared, dict, f"{connector}.{tname} missing input_schema")
                mcp_tool = listed.get(tname)
                self.assertIsNotNone(mcp_tool, tname)
                mcp_schema = getattr(mcp_tool, "inputSchema", None) or getattr(mcp_tool, "input_schema", None)
                self.assertEqual(
                    _worker_args_schema(declared),
                    _worker_args_schema(mcp_schema or {}),
                    f"schema drift for {connector}.{tname}",
                )


if __name__ == "__main__":
    unittest.main()
