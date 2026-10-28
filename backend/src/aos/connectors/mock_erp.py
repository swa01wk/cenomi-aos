"""Mock ERP as an MCP server: categories, suppliers, supplier history and purchase orders.

Tool names and arguments match what the Oracle Fusion adapter will expose, so swapping the
connector is configuration. Storage follows the Fusion tables (EGP_CATEGORIES_B, POZ_SUPPLIERS,
PO_APPROVED_SUPPLIER_LIST, PO_HEADERS_ALL, ...); the tools return the same flat shapes the packs
declare, with Fusion's codes as ids (category code, supplier number, PO number). Every tool takes
the broker token the gateway minted for that one call. Tools prefixed ``admin_`` are demo
controls; no pack declares them, so the gateway can never call them on an agent's behalf.
"""

from __future__ import annotations

import argparse
import os
import re
from datetime import datetime, timezone
from decimal import Decimal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from .base import ConnectorConfig, ConnectorError, Faults, Store, stall
from .mock_erp_seed import PRC_BU, SCHEMA, seed

AOS_PO = "AOS"  # PO_HEADERS_ALL.ATTRIBUTE_CATEGORY on orders AOS created; ATTRIBUTE1 is the reference
FIRST_AOS_PO = 778201

_SUPPLIERS_IN_CATEGORY = """
select s.SEGMENT1 as id, s.VENDOR_NAME as name, site.EMAIL_ADDRESS as email, c.CATEGORY_CODE as category_id
from PO_APPROVED_SUPPLIER_LIST asl
join EGP_CATEGORIES_B c on c.CATEGORY_ID = asl.CATEGORY_ID
join POZ_SUPPLIERS s on s.VENDOR_ID = asl.VENDOR_ID
join POZ_SUPPLIER_SITES_ALL_M site on site.VENDOR_SITE_ID = asl.VENDOR_SITE_ID
where c.CATEGORY_CODE = ? and asl.ASL_STATUS = 'Approved' and asl.DISABLE_FLAG = 'N'
  and s.ENABLED_FLAG = 'Y' and site.PURCHASING_SITE_FLAG = 'Y' and site.INACTIVE_DATE is null
order by s.SEGMENT1
"""

_SUPPLIER_HISTORY = """
select h.SEGMENT1 as po_number,
  (select c.CATEGORY_CODE from PO_LINES_ALL l join EGP_CATEGORIES_B c on c.CATEGORY_ID = l.CATEGORY_ID
     where l.PO_HEADER_ID = h.PO_HEADER_ID order by l.LINE_NUM limit 1) as category_id,
  substr(h.CREATION_DATE, 1, 10) as ordered_on,
  (select case when count(*) > 0 and sum(substr(r.TRANSACTION_DATE, 1, 10) > ll.NEED_BY_DATE) = 0 then 1 else 0 end
     from RCV_TRANSACTIONS r join PO_LINE_LOCATIONS_ALL ll on ll.LINE_LOCATION_ID = r.PO_LINE_LOCATION_ID
     where r.PO_HEADER_ID = h.PO_HEADER_ID and r.TRANSACTION_TYPE = 'RECEIVE') as on_time
from PO_HEADERS_ALL h join POZ_SUPPLIERS s on s.VENDOR_ID = h.VENDOR_ID
where s.SEGMENT1 = ? and h.TYPE_LOOKUP_CODE = 'STANDARD' and h.DOCUMENT_STATUS = 'CLOSED'
order by ordered_on
"""

_CATEGORY_TEXT = """
select c.CATEGORY_CODE as id, tl.CATEGORY_NAME as name,
  tl.CATEGORY_NAME || ' ' || coalesce(tl.DESCRIPTION, '') || ' ' ||
  coalesce((select group_concat(i.DESCRIPTION, ' ') from EGP_ITEM_CATEGORIES ic
            join EGP_SYSTEM_ITEMS_B i on i.INVENTORY_ITEM_ID = ic.INVENTORY_ITEM_ID
            where ic.CATEGORY_ID = c.CATEGORY_ID and i.INVENTORY_ITEM_STATUS_CODE = 'Active'), '') as text
from EGP_CATEGORIES_B c join EGP_CATEGORIES_TL tl on tl.CATEGORY_ID = c.CATEGORY_ID and tl.LANGUAGE = 'US'
where c.ENABLED_FLAG = 'Y'
order by c.CATEGORY_CODE
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _stem(word: str) -> str:
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith(("ches", "shes", "sses", "xes")):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _words(text: str) -> set[str]:
    return {_stem(w) for w in re.findall(r"[a-z0-9]+", text.lower())}


def _number(text: str) -> int | float:
    value = Decimal(text)
    return int(value) if value == value.to_integral_value() else float(value)


def _po_view(store: Store, header: dict) -> dict:
    lines = store.q("select l.ITEM_DESCRIPTION, l.QUANTITY, l.UNIT_PRICE, l.UOM_CODE, ll.NEED_BY_DATE,"
                    " ll.NOTE_TO_RECEIVER from PO_LINES_ALL l"
                    " left join PO_LINE_LOCATIONS_ALL ll on ll.PO_LINE_ID = l.PO_LINE_ID and ll.SHIPMENT_NUM = 1"
                    " where l.PO_HEADER_ID = ? order by l.LINE_NUM", (header["PO_HEADER_ID"],))
    supplier = store.one("select SEGMENT1 from POZ_SUPPLIERS where VENDOR_ID = ?", (header["VENDOR_ID"],))
    view_lines = []
    total = Decimal("0")
    for line in lines:
        total += Decimal(line["QUANTITY"]) * Decimal(line["UNIT_PRICE"])
        entry = {"item": line["ITEM_DESCRIPTION"], "quantity": _number(line["QUANTITY"]),
                 "unit_price": _number(line["UNIT_PRICE"])}
        if line["UOM_CODE"]:
            entry["uom"] = line["UOM_CODE"]
        view_lines.append(entry)
    first = lines[0] if lines else {}
    return {"id": header["SEGMENT1"], "reference": header["ATTRIBUTE1"], "idempotency_key": header["ATTRIBUTE2"],
            "supplier_id": supplier["SEGMENT1"] if supplier else None, "ship_to": first.get("NOTE_TO_RECEIVER"),
            "need_by": first.get("NEED_BY_DATE"), "currency": header["CURRENCY_CODE"], "lines": view_lines,
            "total": str(total), "created_at": header["CREATION_DATE"]}


def build_server(cfg: ConnectorConfig) -> tuple[MCPServer, Store]:
    store = Store(cfg.db_path, SCHEMA)
    seed(store)
    server = MCPServer("mock_erp", version="0.2.0",
                       instructions="Mock ERP (Oracle Fusion tables) for the AOS POC. Every call needs a broker token.")

    def guard(token: str | None, resource: str, action: str, tool: str) -> None:
        try:
            cfg.check(token, resource, action, tool=tool)
        except ConnectorError as exc:
            raise ToolError(str(exc)) from exc

    def aos_header(where: str, args: tuple) -> dict | None:
        return store.one(f"select * from PO_HEADERS_ALL where ATTRIBUTE_CATEGORY = ? and ({where})", (AOS_PO, *args))

    @server.tool()
    def browse_categories(query: str = "", token: str | None = None) -> dict:
        """List ERP categories whose name, description or items contain every word of the query."""
        guard(token, "erp_supplier", "read", "browse_categories")
        wanted = _words(query)
        items = [{"id": row["id"], "name": row["name"]} for row in store.q(_CATEGORY_TEXT)
                 if wanted <= _words(row["text"])]
        return {"items": items}

    @server.tool()
    def search_suppliers(category_id: str, token: str | None = None) -> dict:
        """Active suppliers on the approved supplier list for a category."""
        guard(token, "erp_supplier", "read", "search_suppliers")
        rows = store.q(_SUPPLIERS_IN_CATEGORY, (category_id,))
        if cfg.faults.oversized_reads:
            rows = rows * 500
        return {"items": rows, "source": f"erp://category/{category_id}/suppliers"}

    @server.tool()
    def get_supplier_history(supplier_id: str, token: str | None = None) -> dict:
        """Past (received and closed) orders for a supplier, with the on-time rate."""
        guard(token, "erp_supplier", "read", "get_supplier_history")
        rows = store.q(_SUPPLIER_HISTORY, (supplier_id,))
        rate = round(100 * sum(r["on_time"] for r in rows) / len(rows), 1) if rows else None
        return {"supplier_id": supplier_id, "orders": rows, "past_pos": len(rows), "on_time_pct": rate,
                "source": f"erp://supplier/{supplier_id}/history"}

    @server.tool()
    def find_po(reference: str, token: str | None = None) -> dict:
        """Look a purchase order up by the reference AOS wrote on it. Used to reconcile unknown outcomes."""
        guard(token, "erp_po", "read", "find_po")
        row = aos_header("ATTRIBUTE1 = ?", (reference,))
        return {"found": row is not None, "po": _po_view(store, row) if row else None}

    @server.tool()
    async def create_po(supplier_id: str, ship_to: str, need_by: str, currency: str, lines: list[dict],
                        reference: str, idempotency_key: str, token: str | None = None) -> dict:
        """Create a purchase order. Idempotent: the same reference or key returns the existing order."""
        guard(token, "erp_po", "create", "create_po")
        existing = aos_header("ATTRIBUTE1 = ? or ATTRIBUTE2 = ?", (reference, idempotency_key))
        if existing:
            return {**_po_view(store, existing), "duplicate": True}
        if cfg.faults.take("fail_validation"):
            raise ToolError("validation: supplier site is inactive for purchasing (injected fault)")
        vendor = store.one("select s.VENDOR_ID, site.VENDOR_SITE_ID, site.TERMS_ID from POZ_SUPPLIERS s"
                           " join POZ_SUPPLIER_SITES_ALL_M site on site.VENDOR_ID = s.VENDOR_ID"
                           " where s.SEGMENT1 = ? and s.ENABLED_FLAG = 'Y' and site.PURCHASING_SITE_FLAG = 'Y'"
                           " and site.INACTIVE_DATE is null order by site.VENDOR_SITE_ID limit 1", (supplier_id,))
        if not vendor:
            raise ToolError(f"validation: unknown or inactive supplier {supplier_id}")
        if not lines:
            raise ToolError("validation: a purchase order needs at least one line")
        parsed = []
        for line in lines:
            try:
                qty, price = Decimal(str(line["quantity"])), Decimal(str(line["unit_price"]))
                parsed.append((str(line.get("item") or line.get("description") or "Item"), str(qty), str(price),
                               line.get("uom")))
            except (KeyError, ArithmeticError) as exc:
                raise ToolError(f"validation: bad line {line!r}") from exc
        count = store.one("select count(*) as n from PO_HEADERS_ALL where ATTRIBUTE_CATEGORY = ?", (AOS_PO,))["n"]
        location = store.one("select LOCATION_ID from HR_LOCATIONS_ALL where lower(LOCATION_CODE) = lower(?)"
                             " or lower(DESCRIPTION) = lower(?)", (ship_to, ship_to))
        store.x("begin")
        try:
            hid = store.x("insert into PO_HEADERS_ALL(SEGMENT1, TYPE_LOOKUP_CODE, PRC_BU_ID, VENDOR_ID, VENDOR_SITE_ID,"
                          " CURRENCY_CODE, TERMS_ID, DOCUMENT_STATUS, APPROVED_FLAG, ATTRIBUTE_CATEGORY, ATTRIBUTE1,"
                          " ATTRIBUTE2, CREATION_DATE) values (?, 'STANDARD', ?, ?, ?, ?, ?, 'OPEN', 'Y', ?, ?, ?, ?)",
                          (f"PO-{FIRST_AOS_PO + count}", PRC_BU, vendor["VENDOR_ID"], vendor["VENDOR_SITE_ID"],
                           currency, vendor["TERMS_ID"], AOS_PO, reference, idempotency_key, _now()))
            for num, (desc, qty, price, uom) in enumerate(parsed, start=1):
                item = store.one("select i.INVENTORY_ITEM_ID, ic.CATEGORY_ID from EGP_SYSTEM_ITEMS_B i"
                                 " left join EGP_ITEM_CATEGORIES ic on ic.INVENTORY_ITEM_ID = i.INVENTORY_ITEM_ID"
                                 " where lower(i.DESCRIPTION) = lower(?) limit 1", (desc,))
                lid = store.x("insert into PO_LINES_ALL(PO_HEADER_ID, LINE_NUM, ITEM_ID, ITEM_DESCRIPTION, CATEGORY_ID,"
                              " UOM_CODE, QUANTITY, UNIT_PRICE) values (?, ?, ?, ?, ?, ?, ?, ?)",
                              (hid, num, item["INVENTORY_ITEM_ID"] if item else None, desc,
                               item["CATEGORY_ID"] if item else None, uom, qty, price))
                store.x("insert into PO_LINE_LOCATIONS_ALL(PO_LINE_ID, PO_HEADER_ID, SHIPMENT_NUM, QUANTITY,"
                        " NEED_BY_DATE, SHIP_TO_LOCATION_ID, NOTE_TO_RECEIVER) values (?, ?, 1, ?, ?, ?, ?)",
                        (lid, hid, qty, need_by, location["LOCATION_ID"] if location else None, ship_to))
            store.x("commit")
        except BaseException:
            store.x("rollback")
            raise
        if cfg.faults.take("timeout_after_commit"):
            await stall(cfg)  # committed, but the caller times out before hearing back
        header = store.one("select * from PO_HEADERS_ALL where PO_HEADER_ID = ?", (hid,))
        return {**_po_view(store, header), "duplicate": False}

    @server.tool()
    def admin_set_faults(timeout_after_commit: int = 0, timeout_delay_s: float = 30.0, fail_validation: int = 0,
                         oversized_reads: bool = False) -> dict:
        """Demo control: arm fault switches. Not declared in any pack, so never reachable by an agent."""
        cfg.faults = Faults(timeout_after_commit, timeout_delay_s, fail_validation, oversized_reads)
        return {"armed": cfg.faults.__dict__}

    @server.tool()
    def admin_list_pos() -> dict:
        """Demo control: every purchase order AOS created, to prove nothing was created twice."""
        rows = store.q("select * from PO_HEADERS_ALL where ATTRIBUTE_CATEGORY = ? order by SEGMENT1", (AOS_PO,))
        return {"items": [_po_view(store, r) for r in rows]}

    return server, store


def main() -> None:
    parser = argparse.ArgumentParser(description="Mock ERP MCP server")
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8101")))
    parser.add_argument("--db", default=os.environ.get("MOCK_ERP_DB", "mock_erp.sqlite"))
    args = parser.parse_args()
    cfg = ConnectorConfig(name="mock_erp", secret=os.environ.get("MOCK_ERP_SECRET", "dev-erp-secret"), db_path=args.db)
    server, _ = build_server(cfg)
    server.run("streamable-http", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
