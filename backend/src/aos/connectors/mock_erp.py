"""Mock ERP as an MCP server: categories, suppliers, supplier history and purchase orders.

Tool names and arguments match what the Oracle Fusion adapter will expose, so swapping the
connector is configuration. Every tool takes the broker token the gateway minted for that one
call. Tools prefixed ``admin_`` are demo controls; no pack declares them, so the gateway can
never call them on an agent's behalf.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from decimal import Decimal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from .base import ConnectorConfig, ConnectorError, Faults, Store, stall


SCHEMA = """
create table if not exists category(id text primary key, name text not null);
create table if not exists supplier(id text primary key, name text not null, category_id text not null,
    email text not null, status text not null default 'active');
create table if not exists history(id integer primary key, supplier_id text not null, po_number text not null,
    category_id text not null, ordered_on text not null, on_time integer not null);
create table if not exists po(id text primary key, reference text unique not null, idempotency_key text unique,
    supplier_id text not null, ship_to text not null, need_by text not null, currency text not null,
    lines text not null, total text not null, created_at text not null);
"""

SEED_CATEGORIES = [("CAT-JAN-EQ", "Janitorial equipment"), ("CAT-FAC-SVC", "Facility services")]
# Item words a requester uses that the category name doesn't carry; every query word must hit name or terms.
CATEGORY_TERMS = {
    "CAT-JAN-EQ": "cleaning trolley trolleys cart carts mop mops bucket buckets custodial",
    "CAT-FAC-SVC": "cleaning maintenance service services contract",
}
SEED_SUPPLIERS = [
    ("SUP-10482", "Najd Supplies", "CAT-JAN-EQ", "sales@najd.example"),
    ("SUP-10217", "Al Noor Trading", "CAT-JAN-EQ", "rfq@alnoor.example"),
    ("SUP-10355", "Desert Clean", "CAT-JAN-EQ", "tenders@desertclean.example"),
    ("SUP-10790", "Gulf Janitorial", "CAT-JAN-EQ", "info@gulfjanitorial.example"),
    ("SUP-10611", "Riyadh Facility Mart", "CAT-JAN-EQ", "orders@rfm.example"),
]
# (supplier, po, on_time) — past janitorial orders that drive the ranking signals.
SEED_HISTORY = [
    ("SUP-10482", "PO-771204", 1), ("SUP-10482", "PO-772015", 1), ("SUP-10482", "PO-773301", 1),
    ("SUP-10217", "PO-772640", 1),
    ("SUP-10355", "PO-771950", 1), ("SUP-10355", "PO-773012", 0),
    ("SUP-10611", "PO-770880", 0),
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _seed(store: Store) -> None:
    if store.one("select 1 as x from category limit 1"):
        return
    for cid, name in SEED_CATEGORIES:
        store.x("insert into category values (?, ?)", (cid, name))
    for sid, name, cat, email in SEED_SUPPLIERS:
        store.x("insert into supplier(id, name, category_id, email) values (?, ?, ?, ?)", (sid, name, cat, email))
    for i, (sid, po, on_time) in enumerate(SEED_HISTORY):
        store.x("insert into history(supplier_id, po_number, category_id, ordered_on, on_time) values (?,?,?,?,?)",
                (sid, po, "CAT-JAN-EQ", f"2025-{(i % 9) + 1:02d}-15", on_time))


def _po_view(row: dict) -> dict:
    return {**row, "lines": json.loads(row["lines"])}


def build_server(cfg: ConnectorConfig) -> tuple[MCPServer, Store]:
    store = Store(cfg.db_path, SCHEMA)
    _seed(store)
    server = MCPServer("mock_erp", version="0.1.0",
                       instructions="Mock ERP for the AOS POC. Every call needs a broker token.")

    def guard(token: str | None, resource: str, action: str, tool: str) -> None:
        try:
            cfg.check(token, resource, action, tool=tool)
        except ConnectorError as exc:
            raise ToolError(str(exc)) from exc

    @server.tool()
    def browse_categories(query: str = "", token: str | None = None) -> dict:
        """List ERP categories whose name or search terms contain every word of the query."""
        guard(token, "erp_supplier", "read", "browse_categories")
        words = query.lower().split()
        items = []
        for row in store.q("select id, name from category order by id", ()):
            haystack = f"{row['name']} {CATEGORY_TERMS.get(row['id'], '')}".lower()
            if all(w in haystack for w in words):
                items.append(row)
        return {"items": items}

    @server.tool()
    def search_suppliers(category_id: str, token: str | None = None) -> dict:
        """Active suppliers mapped to a category."""
        guard(token, "erp_supplier", "read", "search_suppliers")
        rows = store.q("select id, name, email, category_id from supplier where category_id = ? and status = 'active'"
                       " order by id", (category_id,))
        if cfg.faults.oversized_reads:
            rows = rows * 500
        return {"items": rows, "source": f"erp://category/{category_id}/suppliers"}

    @server.tool()
    def get_supplier_history(supplier_id: str, token: str | None = None) -> dict:
        """Past orders for a supplier, with the on-time rate."""
        guard(token, "erp_supplier", "read", "get_supplier_history")
        rows = store.q("select po_number, category_id, ordered_on, on_time from history where supplier_id = ?"
                       " order by ordered_on", (supplier_id,))
        rate = round(100 * sum(r["on_time"] for r in rows) / len(rows), 1) if rows else None
        return {"supplier_id": supplier_id, "orders": rows, "past_pos": len(rows), "on_time_pct": rate,
                "source": f"erp://supplier/{supplier_id}/history"}

    @server.tool()
    def find_po(reference: str, token: str | None = None) -> dict:
        """Look a purchase order up by the reference AOS wrote on it. Used to reconcile unknown outcomes."""
        guard(token, "erp_po", "read", "find_po")
        row = store.one("select * from po where reference = ?", (reference,))
        return {"found": row is not None, "po": _po_view(row) if row else None}

    @server.tool()
    async def create_po(supplier_id: str, ship_to: str, need_by: str, currency: str, lines: list[dict],
                        reference: str, idempotency_key: str, token: str | None = None) -> dict:
        """Create a purchase order. Idempotent: the same reference or key returns the existing order."""
        guard(token, "erp_po", "create", "create_po")
        existing = store.one("select * from po where reference = ? or idempotency_key = ?", (reference, idempotency_key))
        if existing:
            return {**_po_view(existing), "duplicate": True}
        if cfg.faults.take("fail_validation"):
            raise ToolError("validation: supplier site is inactive for purchasing (injected fault)")
        if not store.one("select id from supplier where id = ? and status = 'active'", (supplier_id,)):
            raise ToolError(f"validation: unknown or inactive supplier {supplier_id}")
        if not lines:
            raise ToolError("validation: a purchase order needs at least one line")
        total = Decimal("0")
        for line in lines:
            try:
                total += Decimal(str(line["quantity"])) * Decimal(str(line["unit_price"]))
            except (KeyError, ArithmeticError) as exc:
                raise ToolError(f"validation: bad line {line!r}") from exc
        po_id = f"PO-{778201 + len(store.q('select id from po'))}"
        store.x("insert into po values (?,?,?,?,?,?,?,?,?,?)",
                (po_id, reference, idempotency_key, supplier_id, ship_to, need_by, currency, json.dumps(lines),
                 str(total), _now()))
        if cfg.faults.take("timeout_after_commit"):
            await stall(cfg)  # committed, but the caller times out before hearing back
        return {**_po_view(store.one("select * from po where id = ?", (po_id,))), "duplicate": False}

    @server.tool()
    def admin_set_faults(timeout_after_commit: int = 0, timeout_delay_s: float = 30.0, fail_validation: int = 0,
                         oversized_reads: bool = False) -> dict:
        """Demo control: arm fault switches. Not declared in any pack, so never reachable by an agent."""
        cfg.faults = Faults(timeout_after_commit, timeout_delay_s, fail_validation, oversized_reads)
        return {"armed": cfg.faults.__dict__}

    @server.tool()
    def admin_list_pos() -> dict:
        """Demo control: every purchase order, to prove nothing was created twice."""
        return {"items": [_po_view(r) for r in store.q("select * from po order by id")]}

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
