"""Demo-only vendor reply injection (mock_mail admin_simulate_reply → kernel inbound)."""

from __future__ import annotations

import json
import os
from typing import Any

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client


def _tool_payload(result: Any) -> dict[str, Any]:
    if getattr(result, "is_error", False):
        text = result.content[0].text if result.content else "tool error"
        raise RuntimeError(text)
    if not result.content:
        return {}
    text = result.content[0].text
    return json.loads(text) if text and text[0] in "[{\"" else {"raw": text}


async def simulate_vendor_reply_on_thread(
    *,
    mail_mcp_url: str,
    conversation_id: str,
    sender: str,
    body: str,
    subject: str = "",
) -> dict[str, Any]:
    """Place a supplier reply on a mock_mail thread; posts to AOS inbound when AOS_INBOUND_URL is set."""
    async with streamable_http_client(mail_mcp_url) as streams:
        read, write = streams[0], streams[1]
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "admin_simulate_reply",
                {
                    "conversation_id": conversation_id,
                    "sender": sender,
                    "body": body,
                    "subject": subject,
                },
            )
            return _tool_payload(result)


def reply_sender(counterparty_key: str) -> str:
    return f"quotes+{counterparty_key}@vendor.example"


def mailbox_connector_url(connector_urls: dict[str, str]) -> str | None:
    for name, url in connector_urls.items():
        if name.endswith("mail"):
            return url
    return None
