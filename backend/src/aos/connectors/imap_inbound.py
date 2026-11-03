"""Poll a real IMAP inbox for supplier replies and record them on mock_mail threads."""

from __future__ import annotations

import email
import hashlib
import imaplib
import logging
import os
import re
from html import unescape
from email.header import decode_header
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr, parsedate_to_datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .base import Store

log = logging.getLogger("aos.imap_inbound")


def _imap_enabled() -> bool:
    if os.environ.get("AOS_IMAP_POLL", "0").strip().lower() in ("0", "false", "no"):
        return False
    user = os.environ.get("IMAP_USERNAME") or os.environ.get("SMTP_USERNAME") or ""
    password = os.environ.get("IMAP_PASSWORD") or os.environ.get("SMTP_PASSWORD") or ""
    host = _imap_host()
    return bool(user and password and host)


def _imap_host() -> str:
    host = (os.environ.get("IMAP_SERVER") or os.environ.get("SMTP_SERVER") or "").strip()
    if host.startswith("smtp."):
        return "imap." + host[5:]
    return host


def _decode_header_value(raw: str | None) -> str:
    if not raw:
        return ""
    parts: list[str] = []
    for frag, enc in decode_header(raw):
        if isinstance(frag, bytes):
            parts.append(frag.decode(enc or "utf-8", errors="replace"))
        else:
            parts.append(str(frag))
    return " ".join(parts).strip()


def _decode_part_payload(part: email.message.Message) -> str:
    payload = part.get_payload(decode=True)
    if isinstance(payload, bytes):
        return payload.decode(part.get_content_charset() or "utf-8", errors="replace")
    return str(payload or "")


def _html_to_text(html: str) -> str:
    text = unescape(html)
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p\s*>", "\n", text)
    text = re.sub(r"(?i)</div\s*>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def _extract_body(msg: email.message.Message) -> str:
    plain_parts: list[str] = []
    html_parts: list[str] = []
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_disposition() == "attachment":
                continue
            ctype = part.get_content_type()
            if ctype == "text/plain":
                plain_parts.append(_decode_part_payload(part).strip())
            elif ctype == "text/html":
                html_parts.append(_html_to_text(_decode_part_payload(part)))
    else:
        ctype = msg.get_content_type()
        raw = _decode_part_payload(msg).strip()
        if ctype == "text/html":
            html_parts.append(_html_to_text(raw))
        else:
            plain_parts.append(raw)
    for chunk in plain_parts:
        if chunk and chunk not in ("(empty body)",):
            return chunk
    for chunk in html_parts:
        if chunk:
            return chunk
    return ""


def _attachment_names(msg: email.message.Message) -> list[str]:
    names: list[str] = []
    if not msg.is_multipart():
        return names
    for part in msg.walk():
        if part.get_content_disposition() == "attachment":
            name = part.get_filename()
            if name:
                names.append(_decode_header_value(name))
    return names


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _msg_datetime(msg: email.message.Message) -> datetime | None:
    raw = msg.get("Date")
    if not raw:
        return None
    try:
        dt = parsedate_to_datetime(raw)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _normalize_subject(subject: str) -> str:
    s = subject.lower().strip()
    for ch in ("\u2013", "\u2014", "\u2212", "\u2010"):
        s = s.replace(ch, "-")
    while True:
        stripped = False
        for prefix in ("re:", "fwd:", "fw:", "aw:"):
            if s.startswith(prefix):
                s = s[len(prefix) :].strip()
                stripped = True
                break
        if not stripped:
            break
    return " ".join(s.split())


def _supplier_id_in_subject(subject: str) -> str | None:
    import re

    m = re.search(r"\b(SUP-\d+)\b", subject, re.IGNORECASE)
    return m.group(1).upper() if m else None


def _ref_supplier_id(ref: str) -> str | None:
    if ":" not in ref:
        return None
    tail = ref.rsplit(":", 1)[-1].strip().upper()
    return tail if tail.startswith("SUP-") else None


def _pick_sent_row(subject: str, hits: list[dict]) -> dict | None:
    if not hits:
        return None
    sup = _supplier_id_in_subject(subject)
    if sup:
        for row in hits:
            if _ref_supplier_id(str(row.get("ref") or "")) == sup:
                return row
        return None
    if len(hits) == 1:
        return hits[0]
    return None


def _subjects_match(inbound: str, sent: str) -> bool:
    a = _normalize_subject(inbound)
    b = _normalize_subject(sent)
    if not a or not b:
        return False
    if a == b:
        return True
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    if len(shorter) >= 16 and shorter in longer:
        return True
    return False


def _instance_id_in_subject(subject: str, instance_id: str) -> bool:
    return bool(instance_id) and instance_id.lower() in subject.lower()


def _sent_for_from(
    store: Store,
    from_addr: str,
    msg: email.message.Message,
    *,
    instance_id: str | None = None,
) -> dict | None:
    """Pick the RFQ sent row this inbound message belongs to (including follow-ups and resends)."""
    local = from_addr.split("@", 1)[0].lower() if "@" in from_addr else from_addr
    rows = store.q(
        "select * from message where folder = 'sent' and (lower(recipient) = ? or lower(recipient) like ?)"
        " order by coalesce(sent_at, created_at) desc",
        (from_addr, f"{local}@%"),
    )
    if not rows:
        return None
    if instance_id:
        inst = instance_id.strip()
        rows = [r for r in rows if str(r.get("ref") or "").startswith(f"{inst}:")]
        if not rows:
            return None
    msg_dt = _msg_datetime(msg)
    subject = _decode_header_value(msg.get("Subject"))
    after_sent: list[dict] = []
    for sent in rows:
        sent_dt = _parse_iso(sent.get("sent_at") or sent.get("created_at"))
        if msg_dt and sent_dt and msg_dt < sent_dt - timedelta(minutes=2):
            continue
        after_sent.append(sent)
    if not after_sent:
        return None

    for sent in after_sent:
        if _instance_id_in_subject(subject, str(sent.get("ref") or "").split(":")[0]):
            return sent

    subject_hits = [s for s in after_sent if _subjects_match(subject, str(s.get("subject") or ""))]
    picked = _pick_sent_row(subject, subject_hits)
    if picked is not None:
        return picked

    if len(after_sent) == 1:
        return after_sent[0]

    return None


def _sent_for_message(
    store: Store,
    msg: email.message.Message,
    *,
    instance_id: str | None,
) -> dict | None:
    """Match an inbound message to a sent RFQ row (subject-first; used when polling a job inbox)."""
    if not instance_id:
        from_addr = parseaddr(msg.get("From", ""))[1].strip().lower()
        if not from_addr:
            return None
        return _sent_for_from(store, from_addr, msg, instance_id=None)

    inst = instance_id.strip()
    rows = store.q(
        "select * from message where folder = 'sent' and ref like ?"
        " order by coalesce(sent_at, created_at) desc",
        (f"{inst}:%",),
    )
    if not rows:
        return None
    msg_dt = _msg_datetime(msg)
    subject = _decode_header_value(msg.get("Subject"))
    candidates: list[dict] = []
    for sent in rows:
        sent_dt = _parse_iso(sent.get("sent_at") or sent.get("created_at"))
        if msg_dt and sent_dt and msg_dt < sent_dt - timedelta(minutes=2):
            continue
        candidates.append(sent)
    if not candidates:
        return None

    if _instance_id_in_subject(subject, inst):
        for sent in candidates:
            ref_inst = str(sent.get("ref") or "").split(":")[0]
            if ref_inst.lower() == inst.lower():
                return sent

    subject_hits = [s for s in candidates if _subjects_match(subject, str(s.get("subject") or ""))]
    picked = _pick_sent_row(subject, subject_hits)
    if picked is not None:
        return picked

    norm_in = _normalize_subject(subject)
    if f"[{inst.lower()}]" in subject.lower() or inst.lower() in subject.lower():
        inst_hits = subject_hits if subject_hits else candidates
        picked = _pick_sent_row(subject, inst_hits)
        if picked is not None:
            return picked

    if norm_in and any(
        len(_normalize_subject(str(s.get("subject") or ""))) >= 12
        and (
            norm_in in _normalize_subject(str(s.get("subject") or ""))
            or _normalize_subject(str(s.get("subject") or "")) in norm_in
        )
        for s in candidates
    ):
        for sent in candidates:
            s_norm = _normalize_subject(str(sent.get("subject") or ""))
            if len(s_norm) >= 12 and (norm_in in s_norm or s_norm in norm_in):
                return sent

    from_addr = parseaddr(msg.get("From", ""))[1].strip().lower()
    if from_addr:
        return _sent_for_from(store, from_addr, msg, instance_id=inst)
    return None


def _reply_recipients(store: Store, instance_id: str | None = None) -> list[str]:
    if instance_id:
        inst = instance_id.strip()
        rows = store.q(
            "select distinct lower(recipient) as r from message where folder = 'sent'"
            " and recipient like '%@%' and ref like ?",
            (f"{inst}:%",),
        )
    else:
        rows = store.q(
            "select distinct lower(recipient) as r from message where folder = 'sent' and recipient like '%@%'"
        )
    out: list[str] = []
    seen: set[str] = set()
    for row in rows:
        addr = str(row["r"] or "").strip().lower()
        if addr and addr not in seen:
            seen.add(addr)
            out.append(addr)
    return out


def _imap_dedupe_key(msg: email.message.Message, body: str) -> str:
    mid = (msg.get("Message-ID") or "").strip()
    if mid:
        return mid
    subject = _decode_header_value(msg.get("Subject"))
    dt = _msg_datetime(msg)
    stamp = dt.isoformat() if dt else ""
    digest = hashlib.sha256(f"{subject}\n{stamp}\n{body[:4000]}".encode("utf-8", errors="replace")).hexdigest()[:24]
    return f"hash:{digest}"


def _already_ingested(store: Store, *, imap_message_id: str) -> bool:
    if not imap_message_id:
        return False
    return store.one("select 1 from message where imap_message_id = ?", (imap_message_id,)) is not None


def _skip_as_outbound_echo(msg: email.message.Message, sent: dict) -> bool:
    """Gmail Sent often contains our RFQ relay copies — not supplier quotes.

    Demo quotes are sometimes sent with the same subject as the RFQ; only skip when the body
    matches the outbound RFQ text, not on subject alone.
    """
    body = _extract_body(msg).strip()
    out_body = str(sent.get("body") or "").strip()
    if len(body) >= 80 and len(out_body) >= 80 and body[:800] == out_body[:800]:
        return True
    if body and out_body and body == out_body:
        return True
    return False


def _duplicate_inbox_reply(store: Store, *, ref: str, body: str) -> bool:
    row = store.one(
        "select 1 from message where folder = 'inbox' and ref = ? and body = ? limit 1",
        (ref, body),
    )
    return row is not None


def _ingest_imap_message(
    store: Store,
    *,
    notify,
    msg: email.message.Message,
    sent: dict,
    from_addr: str,
) -> bool:
    body = _extract_body(msg)
    imap_mid = _imap_dedupe_key(msg, body)
    if _already_ingested(store, imap_message_id=imap_mid):
        return False
    if not body:
        body = "(empty body)"
    else:
        from .quote_reply_parse import append_parse_hints, parse_quote_reply_text

        body = append_parse_hints(body, parse_quote_reply_text(body))
    if _duplicate_inbox_reply(store, ref=str(sent.get("ref") or ""), body=body):
        return False
    attach = _attachment_names(msg)
    if attach:
        body = body + "\n\nAttachments: " + ", ".join(attach)
    subject = _decode_header_value(msg.get("Subject"))
    mid = "msg-" + __import__("uuid").uuid4().hex[:12]
    store.x(
        "insert into message(id, conversation_id, folder, sender, recipient, subject, body, ref, imap_message_id,"
        " created_at) values (?,?,?,?,?,?,?,?,?,?)",
        (
            mid,
            sent["conversation_id"],
            "inbox",
            from_addr,
            sent["sender"],
            subject or ("RE: " + sent["subject"]),
            body,
            sent["ref"],
            imap_mid or None,
            __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(timespec="seconds"),
        ),
    )
    row = store.one("select * from message where id = ?", (mid,))
    if row is None:
        return False
    notify(row)
    return True


def _ingest_from_imap_message(
    mail: imaplib.IMAP4,
    store: Store,
    *,
    notify,
    msg: email.message.Message,
    instance_id: str | None,
    processed: set[bytes],
    num: bytes,
) -> bool:
    if num in processed:
        return False
    processed.add(num)
    from_addr = parseaddr(msg.get("From", ""))[1].strip().lower()
    if not from_addr:
        return False
    sent = _sent_for_message(store, msg, instance_id=instance_id)
    if sent is None:
        return False
    # Demo: quote typed in Gmail and sent To the test alias — treat supplier as the RFQ recipient row.
    polled_user = (os.environ.get("SMTP_USERNAME") or os.environ.get("IMAP_USERNAME") or "").strip().lower()
    to_addr = parseaddr(msg.get("To", ""))[1].strip().lower()
    test_to = (os.environ.get("AOS_RFQ_TEST_TO") or "").strip().lower()
    if polled_user and from_addr == polled_user:
        if test_to and to_addr == test_to:
            from_addr = str(sent.get("recipient") or from_addr).strip().lower()
        elif to_addr == polled_user:
            sup = _supplier_id_in_subject(_decode_header_value(msg.get("Subject")))
            if sup:
                from_addr = f"quotes+{sup.lower()}@vendor.example"
    if _skip_as_outbound_echo(msg, sent):
        return False
    if _ingest_imap_message(store, notify=notify, msg=msg, sent=sent, from_addr=from_addr):
        try:
            mail.store(num, "+FLAGS", "\\Seen")
        except imaplib.IMAP4.error:
            pass
        return True
    return False


def poll_imap_into_store(
    store: Store,
    *,
    notify,
    instance_id: str | None = None,
) -> dict[str, Any]:
    """Fetch IMAP replies (inbox + demo sent-as-quote) and notify kernel."""
    if not _imap_enabled():
        return {"polled": False, "reason": "imap_not_configured", "ingested": 0}

    recipients = _reply_recipients(store, instance_id)
    if not recipients and not instance_id:
        return {"polled": True, "ingested": 0, "reason": "no_sent_recipients", "instance_id": instance_id}

    host = _imap_host()
    port = int(os.environ.get("IMAP_PORT", "993"))
    user = os.environ.get("IMAP_USERNAME") or os.environ["SMTP_USERNAME"]
    password = os.environ.get("IMAP_PASSWORD") or os.environ["SMTP_PASSWORD"]
    use_ssl = os.environ.get("IMAP_SSL", "1").strip().lower() not in ("0", "false", "no")
    per_recipient = int(os.environ.get("AOS_IMAP_MAX_PER_RECIPIENT", "15"))
    poll_sent = os.environ.get("AOS_IMAP_POLL_SENT", "1").strip().lower() in ("1", "true", "yes")

    ingested = 0
    ingested_sent = 0
    try:
        if use_ssl:
            mail = imaplib.IMAP4_SSL(host, port)
        else:
            mail = imaplib.IMAP4(host, port)
        mail.login(user, password)

        def _collect_ids(folder: str, search_criteria: tuple[str, ...]) -> list[bytes]:
            try:
                mail.select(folder, readonly=True)
            except imaplib.IMAP4.error:
                return []
            try:
                _typ, data = mail.search(None, *search_criteria)
            except imaplib.IMAP4.error:
                return []
            return data[0].split() if data and data[0] else []

        processed: set[bytes] = set()
        inbox_folder = os.environ.get("IMAP_FOLDER", "INBOX")
        seen_nums: list[bytes] = []
        for addr in recipients:
            ids = _collect_ids(inbox_folder, ("FROM", addr))
            if not ids:
                ids = _collect_ids(inbox_folder, ("FROM", f'"{addr}"'))
            batch = ids[-per_recipient:] if len(ids) > per_recipient else ids
            for num in batch:
                if num not in seen_nums:
                    seen_nums.append(num)
        if instance_id:
            for num in _collect_ids(inbox_folder, ("HEADER", "References", instance_id))[-per_recipient:]:
                if num not in seen_nums:
                    seen_nums.append(num)
            polled_user = (os.environ.get("SMTP_USERNAME") or os.environ.get("IMAP_USERNAME") or "").strip()
            if polled_user:
                for num in _collect_ids(inbox_folder, ("TO", polled_user))[-per_recipient:]:
                    if num not in seen_nums:
                        seen_nums.append(num)
            for num in _collect_ids(inbox_folder, ("SUBJECT", instance_id))[-per_recipient:]:
                if num not in seen_nums:
                    seen_nums.append(num)
            scan_all = os.environ.get("AOS_IMAP_SCAN_ALL", "0").strip().lower() in ("1", "true", "yes")
            if scan_all:
                for num in _collect_ids(inbox_folder, ("ALL",))[-50:]:
                    if num not in seen_nums:
                        seen_nums.append(num)
        mail.select(inbox_folder, readonly=True)
        for num in reversed(seen_nums):
            _typ, msg_data = mail.fetch(num, "(RFC822)")
            if not msg_data or not msg_data[0]:
                continue
            raw = msg_data[0][1]
            if not isinstance(raw, bytes):
                continue
            msg = email.message_from_bytes(raw)
            if _ingest_from_imap_message(
                mail, store, notify=notify, msg=msg, instance_id=instance_id, processed=processed, num=num
            ):
                ingested += 1

        if poll_sent and instance_id:
            sent_folder = os.environ.get("IMAP_SENT_FOLDER", "[Gmail]/Sent Mail")
            sent_ids = _collect_ids(sent_folder, ("SINCE", "01-Nov-2025"))
            batch = sent_ids[-40:] if len(sent_ids) > 40 else sent_ids
            mail.select(sent_folder, readonly=True)
            for num in reversed(batch):
                _typ, msg_data = mail.fetch(num, "(RFC822)")
                if not msg_data or not msg_data[0]:
                    continue
                raw = msg_data[0][1]
                if not isinstance(raw, bytes):
                    continue
                msg = email.message_from_bytes(raw)
                if _ingest_from_imap_message(
                    mail, store, notify=notify, msg=msg, instance_id=instance_id, processed=processed, num=num
                ):
                    ingested_sent += 1

        mail.logout()
    except Exception:
        log.exception("imap poll failed")
        return {"polled": True, "ingested": ingested + ingested_sent, "error": "imap_failed"}
    return {"polled": True, "ingested": ingested + ingested_sent, "inbox": ingested, "sent": ingested_sent}


def poll_imap_loop(store: Store, *, notify, interval_s: float = 20.0) -> None:
    import time

    while True:
        time.sleep(interval_s)
        try:
            result = poll_imap_into_store(store, notify=notify)
            if result.get("ingested"):
                log.info("imap: ingested %s replies", result["ingested"])
        except Exception:
            log.exception("imap poll loop error")
