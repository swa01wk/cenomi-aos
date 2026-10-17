"""Mock shared sourcing mailbox as an MCP server.

Mirrors the Microsoft Graph adapter's contract: drafts carry the action's idempotency key in a
header, sending moves a draft to Sent, ``find_message`` looks a send up by that key so the
gateway can reconcile an unknown outcome, and replies raise a signed ``mail.message_received``
notification to the kernel's inbound endpoint.
"""

from __future__ import annotations

import argparse
import json
import os
import threading
import urllib.request
import uuid
from datetime import datetime, timezone

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from .base import ConnectorConfig, ConnectorError, Faults, Store, stall
from .inbound import HEADER, canonical, sign

MAILBOX = "sourcing@procurement.example"
SCHEMA = """
create table if not exists message(id text primary key, conversation_id text not null, folder text not null,
    sender text not null, recipient text not null, subject text not null, body text not null,
    attachments text not null default '[]', idempotency_key text, ref text,
    created_at text not null, sent_at text);
create unique index if not exists message_key on message(idempotency_key, folder);
create table if not exists notification(id integer primary key, payload text not null, signature text not null,
    delivered integer not null default 0, created_at text not null);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def conversation_for(ref: str) -> str:
    """A stable conversation id per (job, supplier) reference, like Graph's conversationId."""
    return "conv-" + uuid.uuid5(uuid.NAMESPACE_URL, f"aos:{ref}").hex[:16]


def _view(row: dict | None) -> dict | None:
    if row is None:
        return None
    return {**row, "attachments": json.loads(row["attachments"])}


def build_server(cfg: ConnectorConfig, *, inbound_url: str | None = None,
                 inbound_secret: str = "dev-inbound-secret") -> tuple[MCPServer, Store]:
    store = Store(cfg.db_path, SCHEMA)
    server = MCPServer("mock_mail", version="0.1.0",
                       instructions="Mock sourcing mailbox for the AOS POC. Every call needs a broker token.")

    def guard(token: str | None, action: str) -> None:
        try:
            cfg.check(token, "mailbox", action)
        except ConnectorError as exc:
            raise ToolError(str(exc)) from exc

    def notify(message: dict) -> dict:
        payload = {"source": "mock_mail", "event": "mail.message_received", "message_id": message["id"],
                   "conversation_id": message["conversation_id"], "ref": message["ref"],
                   "sender": message["sender"], "received_at": message["created_at"]}
        body = canonical(payload)
        sig = sign(body, inbound_secret)
        nid = store.x("insert into notification(payload, signature, created_at) values (?,?,?)",
                      (body.decode(), sig, _now()))
        if inbound_url:
            def post() -> None:
                req = urllib.request.Request(inbound_url, data=body, method="POST",
                                             headers={"Content-Type": "application/json", HEADER: sig})
                try:
                    urllib.request.urlopen(req, timeout=5).read()
                    store.x("update notification set delivered = 1 where id = ?", (nid,))
                except Exception:  # noqa: BLE001 - the daily reconciliation recovers missed notifications
                    pass
            threading.Thread(target=post, daemon=True).start()
        return {"notification_id": nid, "payload": payload, "signature": sig}

    @server.tool()
    def draft_message(to: str, subject: str, body: str, conversation_ref: str, idempotency_key: str,
                      attachments: list[str] | None = None, token: str | None = None) -> dict:
        """Save a draft in the sourcing mailbox. The same idempotency key returns the same draft."""
        guard(token, "draft")
        existing = store.one("select * from message where idempotency_key = ? and folder = 'drafts'", (idempotency_key,))
        if existing:
            return {"draft_id": existing["id"], "conversation_id": existing["conversation_id"], "duplicate": True}
        draft_id = "msg-" + uuid.uuid4().hex[:12]
        conv = conversation_for(conversation_ref)
        store.x("insert into message(id, conversation_id, folder, sender, recipient, subject, body, attachments,"
                " idempotency_key, ref, created_at) values (?,?,?,?,?,?,?,?,?,?,?)",
                (draft_id, conv, "drafts", MAILBOX, to, subject, body, json.dumps(attachments or []),
                 idempotency_key, conversation_ref, _now()))
        return {"draft_id": draft_id, "conversation_id": conv, "duplicate": False}

    @server.tool()
    async def send_message(draft_id: str, idempotency_key: str, token: str | None = None) -> dict:
        """Send a draft. Idempotent: if this key was already sent, the existing message is returned."""
        guard(token, "send")
        sent = store.one("select * from message where idempotency_key = ? and folder = 'sent'", (idempotency_key,))
        if sent:
            return {**_view(sent), "duplicate": True}
        draft = store.one("select * from message where id = ? and folder = 'drafts'", (draft_id,))
        if draft is None:
            raise ToolError(f"not_found: no draft {draft_id}")
        if draft["idempotency_key"] != idempotency_key:
            raise ToolError("validation: the idempotency key does not match the approved draft")
        if cfg.faults.take("fail_validation"):
            raise ToolError("validation: recipient rejected by mail policy (injected fault)")
        store.x("update message set folder = 'sent', sent_at = ? where id = ?", (_now(), draft_id))
        if cfg.faults.take("timeout_after_commit"):
            await stall(cfg)
        return {**_view(store.one("select * from message where id = ?", (draft_id,))), "duplicate": False}

    @server.tool()
    def find_message(idempotency_key: str, token: str | None = None) -> dict:
        """Find a sent message by its idempotency key, to reconcile an unknown send outcome."""
        guard(token, "read")
        msg = _view(store.one("select * from message where idempotency_key = ? and folder = 'sent'",
                              (idempotency_key,)))
        return {"found": msg is not None, "message": msg}

    @server.tool()
    def read_thread(conversation_id: str, token: str | None = None) -> dict:
        """Every sent and received message on a conversation, oldest first."""
        guard(token, "read")
        rows = store.q("select * from message where conversation_id = ? and folder in ('sent', 'inbox')"
                       " order by coalesce(sent_at, created_at), rowid", (conversation_id,))
        return {"conversation_id": conversation_id, "items": [_view(r) for r in rows]}

    @server.tool()
    def admin_simulate_reply(conversation_id: str, sender: str, body: str, subject: str = "") -> dict:
        """Demo control (vendor simulator): a supplier replies on a thread; raises a signed inbound event."""
        first = store.one("select * from message where conversation_id = ? order by created_at limit 1",
                          (conversation_id,))
        if first is None:
            raise ToolError(f"not_found: no conversation {conversation_id}")
        mid = "msg-" + uuid.uuid4().hex[:12]
        store.x("insert into message(id, conversation_id, folder, sender, recipient, subject, body, ref, created_at)"
                " values (?,?,?,?,?,?,?,?,?)",
                (mid, conversation_id, "inbox", sender, MAILBOX, subject or "RE: " + first["subject"], body,
                 first["ref"], _now()))
        return notify(store.one("select * from message where id = ?", (mid,)))

    @server.tool()
    def admin_set_faults(timeout_after_commit: int = 0, timeout_delay_s: float = 30.0, fail_validation: int = 0) -> dict:
        """Demo control: arm fault switches."""
        cfg.faults = Faults(timeout_after_commit, timeout_delay_s, fail_validation)
        return {"armed": cfg.faults.__dict__}

    @server.tool()
    def admin_list(folder: str = "sent") -> dict:
        """Demo control: list a folder, to prove nothing was sent twice."""
        return {"items": [_view(r) for r in store.q("select * from message where folder = ? order by created_at", (folder,))]}

    return server, store


def main() -> None:
    parser = argparse.ArgumentParser(description="Mock mail MCP server")
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8102")))
    parser.add_argument("--db", default=os.environ.get("MOCK_MAIL_DB", "mock_mail.sqlite"))
    args = parser.parse_args()
    cfg = ConnectorConfig(name="mock_mail", secret=os.environ.get("MOCK_MAIL_SECRET", "dev-mail-secret"),
                          db_path=args.db)
    server, _ = build_server(cfg, inbound_url=os.environ.get("AOS_INBOUND_URL"),
                             inbound_secret=os.environ.get("AOS_INBOUND_SECRET", "dev-inbound-secret"))
    server.run("streamable-http", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
