"""Backfill quote artifacts from mock_mail threads (demo reliability)."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from aos.gateway.broker import CredentialBroker, Grant
from aos.gateway.gateway import ToolGateway

from . import clock, ids
from .org import OrgModel

_HINT = re.compile(r"--- Quote fields \(auto-detected from email.*", re.IGNORECASE)


def _excerpt(body: str) -> str:
    m = _HINT.search(body)
    text = body[: m.start()] if m else body
    return text.strip()[:8000]


def _canonical_json(obj: dict[str, Any]) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()


async def _latest_quote_row(
    conn: AsyncConnection, instance_id: str, supplier_id: str
) -> tuple[str, int, dict[str, Any]] | None:
    cur = await conn.execute(
        "select a.id, a.latest_version, v.content from work.artifacts a"
        " join work.artifact_versions v on v.artifact_id = a.id and v.version = a.latest_version"
        " where a.instance_id = %s and a.artifact_type = 'quote' and a.key = %s and a.latest_version >= 1",
        (instance_id, supplier_id),
    )
    row = await cur.fetchone()
    if row is None:
        return None
    content = row[2] if isinstance(row[2], dict) else json.loads(row[2] or "{}")
    return str(row[0]), int(row[1]), content


async def _save_quote_content(
    conn: AsyncConnection,
    *,
    instance_id: str,
    supplier_id: str,
    content: dict[str, Any],
    buyer_id: str,
    existing: tuple[str, int, dict[str, Any]] | None,
) -> bool:
    from .artifacts import parse_artifact_type, validate_artifact_content
    from .instances import _load_definitions

    pv_cur = await conn.execute("select pack_version_id from work.instances where id = %s", (instance_id,))
    pv_row = await pv_cur.fetchone()
    if pv_row is None:
        return False
    defs = await _load_definitions(conn, str(pv_row[0]))
    at = parse_artifact_type(defs, "quote")
    errors = validate_artifact_content(at.spec, content, partial=True)
    if errors:
        return False
    if not content.get("unit_price") and not content.get("total"):
        return False

    content_hash = hashlib.sha256(_canonical_json(content)).hexdigest()
    if existing:
        aid, ver, old = existing
        if old.get("reply_excerpt") and content.get("reply_excerpt") == old.get("reply_excerpt"):
            if content.get("unit_price") == old.get("unit_price"):
                return False
        new_ver = ver + 1
        await conn.execute(
            "insert into work.artifact_versions (artifact_id, version, content, content_hash,"
            " produced_by_kind, produced_by, inputs, sources)"
            " values (%s, %s, %s, %s, 'person', %s, '[]'::jsonb, '[]'::jsonb)",
            (aid, new_ver, Jsonb(content), content_hash, buyer_id),
        )
        await conn.execute(
            "update work.artifacts set latest_version = %s, name = %s where id = %s",
            (new_ver, f"Quote {supplier_id}", aid),
        )
        return True

    artifact_id = ids.new_artifact_id()
    await conn.execute(
        "insert into work.artifacts (id, instance_id, artifact_type, key, name, status, latest_version)"
        " values (%s, %s, 'quote', %s, %s, 'draft', 1)",
        (artifact_id, instance_id, supplier_id, f"Quote {supplier_id}"),
    )
    await conn.execute(
        "insert into work.artifact_versions (artifact_id, version, content, content_hash,"
        " produced_by_kind, produced_by, inputs, sources)"
        " values (%s, 1, %s, %s, 'person', %s, '[]'::jsonb, '[]'::jsonb)",
        (artifact_id, Jsonb(content), content_hash, buyer_id),
    )
    return True


async def sync_quotes_from_mail_threads(
    conn: AsyncConnection,
    gateway: ToolGateway,
    broker: CredentialBroker,
    *,
    org_id: str,
    instance_id: str,
    org: OrgModel,
    packs_dir: Path,
) -> int:
    """Create or enrich quote drafts from supplier inbox messages on sent RFQ threads."""
    from aos.connectors.quote_reply_parse import parse_quote_reply_text

    from . import participants as participant_ops
    from . import quotes as quote_ops

    cur = await conn.execute(
        "select key from work.artifacts where instance_id = %s and artifact_type = 'rfq_email' and key <> ''",
        (instance_id,),
    )
    supplier_ids = [str(r[0]) for r in await cur.fetchall() if r[0]]
    if not supplier_ids:
        return 0

    buyer_id = await participant_ops.resolve_participant(conn, org, instance_id, "buyer", packs_dir=packs_dir)
    if buyer_id is None:
        return 0

    read_token = broker.mint(
        Grant("mock_mail", "mailbox", "read", f"{instance_id}:quote_capture", org_id, "read_thread", "read")
    )
    updated = 0
    now_iso = clock.iso_z(clock.now())

    for supplier_id in supplier_ids:
        conv_id: str | None = None
        for suffix in ("", ":poc_test", ":imap_copy"):
            key = f"{instance_id}:rfq_send:{supplier_id}{suffix}"
            found = await gateway.invoke_read(
                connector="mock_mail",
                tool="find_message",
                args={"idempotency_key": key},
                token=read_token,
            )
            if isinstance(found, dict) and found.get("found") and isinstance(found.get("message"), dict):
                conv_id = str(found["message"].get("conversation_id") or "")
                if conv_id:
                    break
        if not conv_id:
            continue

        thread = await gateway.invoke_read(
            connector="mock_mail",
            tool="read_thread",
            args={"conversation_id": conv_id},
            token=read_token,
        )
        if not isinstance(thread, dict):
            continue
        items = thread.get("items") or []
        inbound = [i for i in items if isinstance(i, dict) and str(i.get("folder")) == "inbox"]
        if not inbound:
            continue

        merged: dict[str, Any] = {}
        excerpt_src = ""
        for msg in inbound:
            body = str(msg.get("body") or "")
            if not body.strip():
                continue
            parsed = parse_quote_reply_text(body)
            for k, v in parsed.items():
                merged[k] = v
            if body.strip() and not _HINT.search(body):
                excerpt_src = body
            elif not excerpt_src:
                excerpt_src = _excerpt(body)

        if not merged and not excerpt_src:
            continue

        existing = await _latest_quote_row(conn, instance_id, supplier_id)
        supplier_label = supplier_id
        if existing:
            supplier_label = str(existing[2].get("supplier") or supplier_id)

        unit = merged.get("unit_price")
        total = merged.get("total")
        if unit is None and total is not None:
            unit = total
        if total is None and unit is not None:
            total = unit
        lead = merged.get("lead_time_days")
        if lead is None:
            lead = 0

        content: dict[str, Any] = {
            "supplier": supplier_label,
            "received_at": now_iso,
            "lead_time_days": int(lead),
        }
        if unit is not None:
            content["unit_price"] = unit
        if total is not None:
            content["total"] = total
        if merged.get("warranty_months") is not None:
            content["warranty_months"] = merged["warranty_months"]
        ex = _excerpt(excerpt_src) if excerpt_src else (existing[2].get("reply_excerpt") if existing else "")
        if ex:
            content["reply_excerpt"] = ex

        if existing and not content.get("reply_excerpt"):
            content["reply_excerpt"] = existing[2].get("reply_excerpt") or ""

        if await _save_quote_content(
            conn,
            instance_id=instance_id,
            supplier_id=supplier_id,
            content=content,
            buyer_id=buyer_id,
            existing=existing,
        ):
            updated += 1

    if updated:
        await quote_ops.sync_quote_count_attribute(conn, instance_id)
        from . import events as workflow_events

        await workflow_events.evaluate_attribute_triggers(
            conn,
            org,
            instance_id,
            changed={"quote_count"},
            packs_dir=packs_dir,
        )
    return updated


async def _latest_proposal_row(
    conn: AsyncConnection, instance_id: str, supplier_id: str
) -> tuple[str, int, dict[str, Any]] | None:
    from aos.connectors.demo_proposal_fill import demo_supplier_display_name

    display = demo_supplier_display_name(supplier_id)
    cur = await conn.execute(
        "select a.id, a.latest_version, v.content from work.artifacts a"
        " join work.artifact_versions v on v.artifact_id = a.id and v.version = a.latest_version"
        " where a.instance_id = %s and a.artifact_type = 'proposal' and a.latest_version >= 1"
        " and (a.key = %s or v.content->>'supplier' in (%s, %s))"
        " order by a.latest_version desc limit 1",
        (instance_id, supplier_id, supplier_id, display),
    )
    row = await cur.fetchone()
    if row is None:
        return None
    content = row[2] if isinstance(row[2], dict) else json.loads(row[2] or "{}")
    return str(row[0]), int(row[1]), content


async def _save_proposal_content(
    conn: AsyncConnection,
    *,
    instance_id: str,
    supplier_id: str,
    content: dict[str, Any],
    buyer_id: str,
    existing: tuple[str, int, dict[str, Any]] | None,
) -> bool:
    from .artifacts import parse_artifact_type, validate_artifact_content
    from .instances import _load_definitions

    pv_cur = await conn.execute("select pack_version_id from work.instances where id = %s", (instance_id,))
    pv_row = await pv_cur.fetchone()
    if pv_row is None:
        return False
    defs = await _load_definitions(conn, str(pv_row[0]))
    at = parse_artifact_type(defs, "proposal")
    allowed = set(at.spec.fields)
    raw = dict(content)
    kind = str(raw.get("reply_kind") or "ack")
    content = {k: v for k, v in raw.items() if k in allowed}
    if "reply_kind" not in allowed and raw.get("notes") and not content.get("notes"):
        content["notes"] = raw["notes"]
    errors = validate_artifact_content(at.spec, content, partial=True)
    if errors:
        return False
    if "reply_kind" in allowed:
        kind = str(content.get("reply_kind") or kind)
        if kind not in ("ack", "question", "proposal"):
            return False
    if kind == "proposal" and not content.get("unit_price") and not content.get("total"):
        return False

    content_hash = hashlib.sha256(_canonical_json(content)).hexdigest()
    if existing:
        aid, ver, old = existing
        if (
            old.get("reply_excerpt") == content.get("reply_excerpt")
            and old.get("notes") == content.get("notes")
            and old.get("total") == content.get("total")
        ):
            return False
        new_ver = ver + 1
        await conn.execute(
            "insert into work.artifact_versions (artifact_id, version, content, content_hash,"
            " produced_by_kind, produced_by, inputs, sources)"
            " values (%s, %s, %s, %s, 'person', %s, '[]'::jsonb, '[]'::jsonb)",
            (aid, new_ver, Jsonb(content), content_hash, buyer_id),
        )
        await conn.execute(
            "update work.artifacts set latest_version = %s, name = %s, key = %s where id = %s",
            (new_ver, f"Proposal {supplier_id}", supplier_id, aid),
        )
        return True

    artifact_id = ids.new_artifact_id()
    await conn.execute(
        "insert into work.artifacts (id, instance_id, artifact_type, key, name, status, latest_version)"
        " values (%s, %s, 'proposal', %s, %s, 'draft', 1)",
        (artifact_id, instance_id, supplier_id, f"Proposal {supplier_id}"),
    )
    await conn.execute(
        "insert into work.artifact_versions (artifact_id, version, content, content_hash,"
        " produced_by_kind, produced_by, inputs, sources)"
        " values (%s, 1, %s, %s, 'person', %s, '[]'::jsonb, '[]'::jsonb)",
        (artifact_id, Jsonb(content), content_hash, buyer_id),
    )
    return True


async def _find_conversation_for_supplier(
    gateway: ToolGateway,
    read_token: str,
    instance_id: str,
    supplier_id: str,
) -> list[dict[str, Any]]:
    for suffix in ("", ":poc_test", ":imap_copy"):
        key = f"{instance_id}:rfq_send:{supplier_id}{suffix}"
        found = await gateway.invoke_read(
            connector="mock_mail",
            tool="find_message",
            args={"idempotency_key": key},
            token=read_token,
        )
        if isinstance(found, dict) and found.get("found") and isinstance(found.get("message"), dict):
            conv_id = str(found["message"].get("conversation_id") or "")
            if not conv_id:
                continue
            thread = await gateway.invoke_read(
                connector="mock_mail",
                tool="read_thread",
                args={"conversation_id": conv_id},
                token=read_token,
            )
            if isinstance(thread, dict):
                items = thread.get("items") or []
                return [i for i in items if isinstance(i, dict) and str(i.get("folder")) == "inbox"]
    return []


async def sync_proposals_from_mail_threads(
    conn: AsyncConnection,
    gateway: ToolGateway,
    broker: CredentialBroker,
    *,
    org_id: str,
    instance_id: str,
    org: OrgModel,
    packs_dir: Path,
) -> int:
    """Create or enrich proposal drafts from supplier inbox messages on sent RFP invitation threads."""
    from aos.connectors.demo_proposal_fill import (
        build_demo_proposal_content,
        is_agent_placeholder_proposal,
    )
    from aos.connectors.proposal_reply_parse import classify_rfp_reply

    from . import participants as participant_ops
    from . import quotes as quote_ops

    cur = await conn.execute(
        "select key from work.artifacts where instance_id = %s and artifact_type = 'rfp_invitation' and key <> ''",
        (instance_id,),
    )
    supplier_ids = [str(r[0]) for r in await cur.fetchall() if r[0]]
    if not supplier_ids:
        return 0

    buyer_id = await participant_ops.resolve_participant(conn, org, instance_id, "buyer", packs_dir=packs_dir)
    if buyer_id is None:
        return 0

    read_token = broker.mint(
        Grant("mock_mail", "mailbox", "read", f"{instance_id}:proposal_capture", org_id, "read_thread", "read")
    )
    updated = 0
    now_iso = clock.iso_z(clock.now())

    for supplier_id in supplier_ids:
        inbound = await _find_conversation_for_supplier(gateway, read_token, instance_id, supplier_id)
        existing = await _latest_proposal_row(conn, instance_id, supplier_id)
        email_body = ""
        for msg in inbound:
            body = str(msg.get("body") or "")
            if body.strip():
                email_body = body if not _HINT.search(body) else _excerpt(body)

        if not email_body and existing and not is_agent_placeholder_proposal(existing[2]):
            continue
        if not email_body and not existing:
            continue

        kind = classify_rfp_reply(email_body) if email_body else "ack"
        content = build_demo_proposal_content(
            supplier_id,
            email_body,
            received_at=now_iso,
            kind=kind,
        )

        if await _save_proposal_content(
            conn,
            instance_id=instance_id,
            supplier_id=supplier_id,
            content=content,
            buyer_id=buyer_id,
            existing=existing,
        ):
            updated += 1

    if updated:
        await quote_ops.sync_proposal_count_attribute(conn, instance_id)
        await quote_ops.sync_ack_count_attribute(conn, instance_id)
        from . import events as workflow_events

        await workflow_events.evaluate_attribute_triggers(
            conn,
            org,
            instance_id,
            changed={"proposal_count", "ack_count"},
            packs_dir=packs_dir,
        )
    return updated
