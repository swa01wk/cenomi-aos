"""Trigger mock_mail IMAP poll through the gateway (on job snapshot load)."""

from __future__ import annotations

import logging

from aos.gateway.broker import CredentialBroker, Grant
from aos.gateway.gateway import ToolGateway

log = logging.getLogger("aos.mail_poll")


async def poll_imap_via_gateway(
    gateway: ToolGateway,
    broker: CredentialBroker,
    *,
    org_id: str,
    instance_id: str,
) -> None:
    from .imap_inbound import _imap_enabled

    if not _imap_enabled():
        log.info(
            "IMAP poll skipped for %s (set SMTP/IMAP credentials on mock-mail — see .env.example)",
            instance_id,
        )
        return
    try:
        token = broker.mint(
            Grant(
                "mock_mail",
                "mailbox",
                "read",
                f"{instance_id}:imap_poll",
                org_id,
                "poll_imap_inbox",
                "poll",
            )
        )
        await gateway.invoke_read(
            connector="mock_mail",
            tool="poll_imap_inbox",
            args={"instance_id": instance_id},
            token=token,
        )
    except Exception:
        log.debug("imap poll skipped or failed for %s", instance_id, exc_info=True)
