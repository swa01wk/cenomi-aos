"""Buyer-approved RFQ send (POC bridge until M3 request_action + ApprovalCard)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from aos.gateway.broker import CredentialBroker, Grant
from aos.gateway.gateway import InvokeFailure, ToolGateway

from aos.kernel import clock, ids
from aos.kernel.org import OrgModel


class OutboundMailError(Exception):
    def __init__(self, code: str, status: int, title: str, detail: str = "", **extra: Any) -> None:
        self.code = code
        self.status = status
        self.title = title
        self.detail = detail
        self.extra = extra
        super().__init__(title)


@dataclass(frozen=True)
class SendPlan:
    relay_only: bool
    attributes: dict[str, Any]
    emails: list[dict[str, Any]]
    shared_attachment_names: tuple[str, ...] = ()
    quote_reply_minutes: float | None = None
    resend: bool = False
    supplier_ids: tuple[str, ...] | None = None


def _idempotency_key(instance_id: str, supplier_id: str) -> str:
    return f"{instance_id}:rfq_send:{supplier_id}"


def _resend_idempotency_key(instance_id: str, supplier_id: str) -> str:
    return f"{instance_id}:rfq_resend:{supplier_id}:{ids.new_attempt_id()[-12:]}"


def _conversation_ref(instance_id: str, supplier_id: str) -> str:
    return f"{instance_id}:{supplier_id}"


def _demo_short_deadline_enabled() -> bool:
    from aos.kernel.reply_deadline import demo_short_deadline_enabled

    return demo_short_deadline_enabled()


def _polled_smtp_inbox() -> str:
    """Mailbox IMAP polls (API may set AOS_POLLED_INBOX without SMTP secrets)."""
    explicit = (os.environ.get("AOS_POLLED_INBOX") or "").strip()
    if explicit:
        return explicit
    return (os.environ.get("SMTP_USERNAME") or os.environ.get("IMAP_USERNAME") or "").strip()


def _demo_test_inbox_to(supplier_id: str) -> str | None:
    polled = _polled_smtp_inbox()
    to_override = os.environ.get("AOS_RFQ_TEST_TO", "").strip()
    prefer_polled = os.environ.get("AOS_RFQ_TEST_DELIVER_TO_POLLED_INBOX", "1").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    if prefer_polled and polled:
        to_override = polled
    elif not to_override and polled:
        to_override = polled
    if not to_override:
        return None
    route_all = os.environ.get("AOS_RFQ_TEST_ROUTE_ALL", "1").strip().lower() in ("1", "true", "yes")
    supplier_override = os.environ.get("AOS_RFQ_TEST_SUPPLIER_ID", "SUP-11632").strip()
    if route_all or supplier_id == supplier_override:
        return to_override
    return None


def _demo_imap_copy_inbox() -> str | None:
    """When RFQs go to a different address, also SMTP a copy to the mailbox IMAP polls."""
    polled = _polled_smtp_inbox()
    if not polled:
        return None
    primary = os.environ.get("AOS_RFQ_TEST_TO", "").strip() or polled
    if primary.lower() == polled.lower():
        return None
    if os.environ.get("AOS_RFQ_TEST_IMAP_COPY", "1").strip().lower() in ("0", "false", "no"):
        return None
    return polled


def _apply_demo_rfq_send_overrides(content: dict[str, Any], *, quote_reply_minutes: float | None = None) -> None:
    """POC: route one supplier to a real inbox and shorten the reply deadline in the email body."""
    supplier_id = str(content.get("supplier_id") or "")
    test_to = _demo_test_inbox_to(supplier_id)
    if test_to:
        content["to"] = test_to
        # Demo: disambiguate threads when every RFQ shares one subject line.
        subj = str(content.get("subject") or "").strip()
        sid = supplier_id.strip()
        if sid and sid not in subj:
            content["subject"] = f"{subj} [{sid}]"

    if not _demo_short_deadline_enabled():
        return
    body = str(content.get("body") or "")
    if not body:
        return
    from aos.kernel.reply_deadline import (
        DEFAULT_DEMO_REPLY_MINUTES,
        demo_reply_timer_duration,
        format_reply_deadline_line,
    )

    minutes = quote_reply_minutes if quote_reply_minutes is not None else DEFAULT_DEMO_REPLY_MINUTES
    seconds = int(clock.parse_duration(demo_reply_timer_duration(minutes)).total_seconds())
    by = (clock.now() + timedelta(seconds=seconds)).strftime("%Y-%m-%d %H:%M UTC")
    replacement = format_reply_deadline_line(minutes, by=by)
    if re.search(r"(?im)^reply deadline:", body):
        body = re.sub(r"(?im)^reply deadline:.*$", replacement, body, count=1)
    else:
        body = body.rstrip() + "\n\n" + replacement
    content["body"] = body


async def _participant_roles(conn: AsyncConnection, instance_id: str, person_id: str) -> list[str]:
    cur = await conn.execute(
        "select role from work.participants where instance_id = %s and person_id = %s order by role",
        (instance_id, person_id),
    )
    return [str(r[0]) for r in await cur.fetchall()]


def _send_profile_for_state(state: str) -> tuple[str, str, str, str] | None:
    """artifact_type, send_state, awaiting_state, task_template"""
    if state == "rfq_sending":
        return ("rfq_email", "rfq_sending", "awaiting_quotes", "rfq_send")
    if state == "rfp_sending":
        return ("rfp_invitation", "rfp_sending", "awaiting_proposals", "rfp_send")
    return None


async def _outbound_mail_drafts(conn: AsyncConnection, instance_id: str, *, artifact_type: str) -> list[dict[str, Any]]:
    cur = await conn.execute(
        "select a.id, a.latest_version, v.content from work.artifacts a"
        " join work.artifact_versions v on v.artifact_id = a.id and v.version = a.latest_version"
        " where a.instance_id = %s and a.artifact_type = %s"
        " order by a.id",
        (instance_id, artifact_type),
    )
    out: list[dict[str, Any]] = []
    for artifact_id, version, raw in await cur.fetchall():
        content = raw if isinstance(raw, dict) else json.loads(raw or "{}")
        out.append(
            {
                "artifact_id": str(artifact_id),
                "version": int(version),
                "content": content,
            }
        )
    return out


async def _rfq_emails(conn: AsyncConnection, instance_id: str) -> list[dict[str, Any]]:
    return await _outbound_mail_drafts(conn, instance_id, artifact_type="rfq_email")


async def _invoke_mail(
    gateway: ToolGateway,
    broker: CredentialBroker,
    *,
    org_id: str,
    instance_id: str,
    attempt_id: str,
    tool: str,
    action: str,
    args: dict[str, Any],
) -> dict[str, Any]:
    token = broker.mint(
        Grant("mock_mail", "mailbox", action, f"{instance_id}:{tool}", org_id, tool, attempt_id)
    )
    result = await gateway.invoke_read(connector="mock_mail", tool=tool, args=args, token=token)
    if isinstance(result, InvokeFailure):
        raise OutboundMailError(
            "connector_failed",
            502,
            "Could not send email",
            result.message or "The mail connector failed.",
        )
    content = result.content
    if not isinstance(content, dict):
        raise OutboundMailError("connector_failed", 502, "Could not send email", "Unexpected mail response.")
    return content


async def plan_send_rfqs(
    conn: AsyncConnection,
    *,
    org_id: str,
    instance_id: str,
    person_id: str,
    supplier_ids: list[str] | None = None,
    resend: bool = False,
) -> SendPlan:
    roles = await _participant_roles(conn, instance_id, person_id)
    if "buyer" not in roles:
        raise OutboundMailError(
            "not_permitted",
            403,
            "Not allowed to send",
            "Only the buyer on this job can approve and send RFQs.",
        )

    inst_cur = await conn.execute(
        "select state, status, attributes from work.instances where id = %s and org_id = %s",
        (instance_id, org_id),
    )
    inst = await inst_cur.fetchone()
    if inst is None:
        raise OutboundMailError("not_found", 404, "Job not found", f"No instance {instance_id!r}.")
    state, status, attributes_raw = inst
    attributes = attributes_raw if isinstance(attributes_raw, dict) else json.loads(attributes_raw or "{}")
    state_str = str(state)
    profile = _send_profile_for_state(state_str)
    if profile is None and state_str == "awaiting_quotes":
        profile = ("rfq_email", "rfq_sending", "awaiting_quotes", "rfq_send")
    elif profile is None and state_str == "awaiting_proposals":
        profile = ("rfp_invitation", "rfp_sending", "awaiting_proposals", "rfp_send")
    if profile is None:
        raise OutboundMailError(
            "conflict",
            409,
            "Not ready to send",
            "Outbound mail can only be sent on the sending step, or re-delivered while awaiting replies.",
        )
    artifact_type, send_state, awaiting, _task_template = profile
    relay_only = state_str == awaiting and bool(attributes.get("rfq_sent_keys"))
    if resend and not relay_only:
        raise OutboundMailError(
            "conflict",
            409,
            "Not ready to resend",
            "Resend is only available while the job is waiting for supplier replies.",
        )
    if state_str != send_state and not relay_only:
        raise OutboundMailError(
            "conflict",
            409,
            "Not ready to send",
            "Outbound mail can only be sent on the sending step, or re-delivered while awaiting replies.",
        )
    if str(status) != "running":
        raise OutboundMailError("conflict", 409, "Job not active", "This job is not running.")

    emails = await _outbound_mail_drafts(conn, instance_id, artifact_type=artifact_type)
    if not emails:
        raise OutboundMailError(
            "validation_failed",
            422,
            "No RFQ drafts",
            "There are no outbound mail drafts to send.",
        )
    from aos.kernel import shared_attachments as shared_att

    shared_names = tuple(await shared_att.filenames_for_instance(conn, instance_id))
    quote_reply_minutes: float | None = None
    if _demo_short_deadline_enabled():
        from aos.kernel.reply_deadline import parse_demo_reply_minutes

        bcur = await conn.execute(
            "select v.content from work.artifacts a"
            " join work.artifact_versions v on v.artifact_id = a.id and v.version = a.latest_version"
            " where a.instance_id = %s and a.artifact_type = 'brief' limit 1",
            (instance_id,),
        )
        brow = await bcur.fetchone()
        if brow is not None:
            brief = brow[0] if isinstance(brow[0], dict) else json.loads(brow[0] or "{}")
            quote_reply_minutes = parse_demo_reply_minutes(brief.get("vendor_reply_deadline"))
    filter_ids = tuple(s.strip() for s in (supplier_ids or []) if str(s).strip()) or None
    if filter_ids:
        emails = [e for e in emails if str(e.get("content", {}).get("supplier_id") or "") in filter_ids]
        if not emails:
            raise OutboundMailError(
                "validation_failed",
                422,
                "No matching RFQ",
                "None of the selected suppliers have an RFQ draft on this job.",
            )
    return SendPlan(
        relay_only=relay_only,
        attributes=attributes,
        emails=emails,
        shared_attachment_names=shared_names,
        quote_reply_minutes=quote_reply_minutes,
        resend=bool(resend),
        supplier_ids=filter_ids,
    )


async def execute_rfqs_mail(
    gateway: ToolGateway,
    broker: CredentialBroker,
    *,
    org_id: str,
    instance_id: str,
    plan: SendPlan,
) -> tuple[list[str], list[dict[str, Any]]]:
    """Gateway / SMTP only — no Postgres row locks (avoids deadlocks with the worker)."""
    attempt_id = ids.new_attempt_id()
    sent_keys: list[str] = []
    receipts: list[dict[str, Any]] = []

    for row in plan.emails:
        content = dict(row["content"])
        _apply_demo_rfq_send_overrides(content, quote_reply_minutes=plan.quote_reply_minutes)
        supplier_id = str(content.get("supplier_id") or "")
        to = str(content.get("to") or "").strip()
        subject = str(content.get("subject") or "").strip()
        body = str(content.get("body") or "").strip()
        if not supplier_id or not to or not subject or not body:
            raise OutboundMailError(
                "validation_failed",
                422,
                "Incomplete RFQ draft",
                f"RFQ for supplier {supplier_id or '?'} is missing to, subject, or body.",
            )
        per_email = content.get("attachments") if isinstance(content.get("attachments"), list) else []
        merged_attachments: list[str] = []
        seen: set[str] = set()
        for name in [*per_email, *plan.shared_attachment_names]:
            s = str(name).strip()
            if s and s not in seen:
                seen.add(s)
                merged_attachments.append(s)
        key = _resend_idempotency_key(instance_id, supplier_id) if plan.resend else _idempotency_key(instance_id, supplier_id)
        draft = await _invoke_mail(
            gateway,
            broker,
            org_id=org_id,
            instance_id=instance_id,
            attempt_id=attempt_id,
            tool="draft_message",
            action="draft",
            args={
                "to": to,
                "subject": subject,
                "body": body,
                "conversation_ref": _conversation_ref(instance_id, supplier_id),
                "idempotency_key": key,
                "attachments": merged_attachments,
            },
        )
        draft_id = str(draft.get("draft_id") or "")
        if not draft_id:
            raise OutboundMailError("connector_failed", 502, "Could not send email", "Draft was not created.")
        sent = await _invoke_mail(
            gateway,
            broker,
            org_id=org_id,
            instance_id=instance_id,
            attempt_id=attempt_id,
            tool="send_message",
            action="send",
            args={"draft_id": draft_id, "idempotency_key": key},
        )
        sent_keys.append(key)
        receipts.append(
            {
                "supplier_id": supplier_id,
                "to": to,
                "idempotency_key": key,
                "message_id": sent.get("id"),
                "duplicate": bool(sent.get("duplicate")),
            }
        )
        # Primary send already targets the demo inbox when routing overrides apply; a second
        # SMTP copy per supplier duplicated every RFQ in the user's mailbox (3 vendors → 6+ emails).
        test_to = _demo_test_inbox_to(supplier_id)
        if test_to and to.strip().lower() != test_to.strip().lower():
            await _deliver_demo_test_inbox(
                gateway,
                broker,
                org_id=org_id,
                instance_id=instance_id,
                attempt_id=attempt_id,
                supplier_id=supplier_id,
                to=test_to,
                subject=subject,
                body=body,
            )
        imap_copy = _demo_imap_copy_inbox()
        if imap_copy and to.strip().lower() != imap_copy.strip().lower():
            await _deliver_demo_test_inbox(
                gateway,
                broker,
                org_id=org_id,
                instance_id=instance_id,
                attempt_id=attempt_id,
                supplier_id=supplier_id,
                to=imap_copy,
                subject=f"[{instance_id}] {subject}",
                body=body,
                key_suffix="imap_copy",
            )
    return sent_keys, receipts


async def _deliver_demo_test_inbox(
    gateway: ToolGateway,
    broker: CredentialBroker,
    *,
    org_id: str,
    instance_id: str,
    attempt_id: str,
    supplier_id: str,
    to: str,
    subject: str,
    body: str,
    key_suffix: str = "poc_test",
) -> None:
    """Second send with a separate idempotency key so a real SMTP copy reaches the POC inbox."""
    key = f"{instance_id}:rfq_send:{supplier_id}:{key_suffix}"
    found = await _invoke_mail(
        gateway,
        broker,
        org_id=org_id,
        instance_id=instance_id,
        attempt_id=attempt_id,
        tool="find_message",
        action="read",
        args={"idempotency_key": key},
    )
    if found.get("found") and found.get("message"):
        sent = found["message"]
        if str(sent.get("recipient") or "") == to:
            return
    draft = await _invoke_mail(
        gateway,
        broker,
        org_id=org_id,
        instance_id=instance_id,
        attempt_id=attempt_id,
        tool="draft_message",
        action="draft",
        args={
            "to": to,
            "subject": subject,
            "body": body,
            "conversation_ref": _conversation_ref(instance_id, supplier_id),
            "idempotency_key": key,
            "attachments": [],
        },
    )
    draft_id = str(draft.get("draft_id") or "")
    if not draft_id:
        raise OutboundMailError("connector_failed", 502, "Could not send test RFQ", "Draft was not created.")
    await _invoke_mail(
        gateway,
        broker,
        org_id=org_id,
        instance_id=instance_id,
        attempt_id=attempt_id,
        tool="send_message",
        action="send",
        args={"draft_id": draft_id, "idempotency_key": key},
    )


async def finalize_send_rfqs(
    conn: AsyncConnection,
    org: OrgModel,
    *,
    org_id: str,
    instance_id: str,
    person_id: str,
    plan: SendPlan,
    sent_keys: list[str],
    receipts: list[dict[str, Any]],
    packs_dir: Path,
) -> dict[str, Any]:
    digest = hashlib.sha256(json.dumps(receipts, sort_keys=True).encode()).hexdigest()[:16]
    if plan.relay_only:
        return {
            "sent_count": len(receipts),
            "receipts": receipts,
            "snapshot_digest": digest,
            "relayed_only": True,
        }

    last_exc: Exception | None = None
    for attempt in range(5):
        try:
            return await _finalize_send_rfqs_once(
                conn,
                org,
                org_id=org_id,
                instance_id=instance_id,
                person_id=person_id,
                plan=plan,
                sent_keys=sent_keys,
                receipts=receipts,
                packs_dir=packs_dir,
                digest=digest,
            )
        except Exception as exc:
            from psycopg.errors import DeadlockDetected

            if not isinstance(exc, DeadlockDetected):
                raise
            last_exc = exc
            await asyncio.sleep(0.05 * (attempt + 1))
    raise OutboundMailError(
        "conflict",
        409,
        "Emails were sent",
        "The messages left your mailbox, but the job could not be updated yet. Reload and click Approve and send again.",
    ) from last_exc


async def _finalize_send_rfqs_once(
    conn: AsyncConnection,
    org: OrgModel,
    *,
    org_id: str,
    instance_id: str,
    person_id: str,
    plan: SendPlan,
    sent_keys: list[str],
    receipts: list[dict[str, Any]],
    packs_dir: Path,
    digest: str,
) -> dict[str, Any]:
    inst_state = ""
    st_cur = await conn.execute("select state from work.instances where id = %s", (instance_id,))
    st_row = await st_cur.fetchone()
    if st_row is not None:
        inst_state = str(st_row[0])
    send_profile = _send_profile_for_state(inst_state) or (
        "rfq_email",
        "rfq_sending",
        "awaiting_quotes",
        "rfq_send",
    )
    _artifact_type, send_state, _awaiting, task_template = send_profile
    tcur = await conn.execute(
        "select id from work.tasks where instance_id = %s and template = %s and region is null"
        " order by created_at desc limit 1 for update",
        (instance_id, task_template),
    )
    task_row = await tcur.fetchone()
    await conn.execute("select id from work.instances where id = %s for update", (instance_id,))

    inst_cur = await conn.execute(
        "select state, status from work.instances where id = %s and org_id = %s",
        (instance_id, org_id),
    )
    inst = await inst_cur.fetchone()
    if inst is None:
        raise OutboundMailError("not_found", 404, "Job not found", f"No instance {instance_id!r}.")
    state, status = str(inst[0]), str(inst[1])
    if state != send_state or status != "running":
        if plan.attributes.get("rfq_sent_keys") == sent_keys:
            return {
                "sent_count": len(receipts),
                "receipts": receipts,
                "snapshot_digest": digest,
                "already_applied": True,
            }
        raise OutboundMailError(
            "conflict",
            409,
            "Job moved on",
            "Reload the job; the emails were sent but the workflow step may already be complete.",
        )

    attributes = {**plan.attributes, "invited_count": len(sent_keys), "rfq_sent_keys": sent_keys}
    await conn.execute(
        "update work.instances set attributes = %s where id = %s",
        (Jsonb(attributes), instance_id),
    )

    if task_row is not None:
        task_id = str(task_row[0])
        await conn.execute(
            "update work.tasks set state = 'COMPLETED', updated_at = %s where id = %s",
            (clock.now(), task_id),
        )
        from aos.kernel import events as workflow_events

        await workflow_events.on_workflow_task_completed(
            conn,
            org,
            instance_id=instance_id,
            task_id=task_id,
            packs_dir=packs_dir,
        )
        from aos.kernel import quotes as quote_ops

        await quote_ops.ensure_quote_deadline_from_brief(conn, instance_id)

    from aos.kernel.task_retry import void_open_task_retry

    pcur = await conn.execute(
        "select id, for_person_id from work.pending_items"
        " where instance_id = %s and status = 'open' and event = 'task.retry'",
        (instance_id,),
    )
    for pending_id, for_person in await pcur.fetchall():
        await void_open_task_retry(
            conn,
            instance_id=instance_id,
            pending_id=str(pending_id),
            for_person_id=str(for_person),
            voided_by=person_id,
        )

    await conn.execute(
        "update work.artifacts set status = 'final'"
        " where instance_id = %s and artifact_type = %s and status = 'draft'",
        (instance_id, _artifact_type),
    )

    return {
        "sent_count": len(receipts),
        "receipts": receipts,
        "snapshot_digest": digest,
    }


async def send_rfqs(
    conn: AsyncConnection,
    org: OrgModel,
    *,
    org_id: str,
    instance_id: str,
    person_id: str,
    gateway: ToolGateway,
    broker: CredentialBroker,
    packs_dir: Path,
) -> dict[str, Any]:
    """Single-transaction entry (tests); HTTP route uses plan / execute / finalize separately."""
    plan = await plan_send_rfqs(conn, org_id=org_id, instance_id=instance_id, person_id=person_id)
    sent_keys, receipts = await execute_rfqs_mail(
        gateway, broker, org_id=org_id, instance_id=instance_id, plan=plan
    )
    return await finalize_send_rfqs(
        conn,
        org,
        org_id=org_id,
        instance_id=instance_id,
        person_id=person_id,
        plan=plan,
        sent_keys=sent_keys,
        receipts=receipts,
        packs_dir=packs_dir,
    )
