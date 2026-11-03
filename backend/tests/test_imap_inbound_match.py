"""IMAP inbound matching and dedupe keys (no live IMAP)."""

from __future__ import annotations

import email
import unittest
from datetime import datetime, timezone

from aos.connectors.base import Store
from aos.connectors.imap_inbound import (
    _imap_dedupe_key,
    _pick_sent_row,
    _sent_for_from,
    _skip_as_outbound_echo,
    _subjects_match,
)


class _MemStore(Store):
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def q(self, sql: str, params: tuple = ()) -> list[dict]:
        if "folder = 'sent'" in sql:
            return [r for r in self.rows if r.get("folder") == "sent"]
        return []

    def one(self, sql: str, params: tuple = ()) -> dict | None:
        if "imap_message_id" in sql:
            key = params[0]
            for r in self.rows:
                if r.get("imap_message_id") == key:
                    return r
        return None

    def x(self, sql: str, params: tuple = ()) -> int:
        return 0


class ImapInboundMatchTests(unittest.TestCase):
    def test_follow_up_without_re_matches_single_rfq(self) -> None:
        store = _MemStore()
        store.rows.append(
            {
                "folder": "sent",
                "recipient": "saad.bn@webknot.in",
                "ref": "QQ-0067:SUP-11632",
                "subject": "RFQ: phones",
                "sent_at": "2026-11-02T08:00:00+00:00",
                "conversation_id": "conv-1",
            }
        )
        raw = (
            "From: saad.bn@webknot.in\r\n"
            "To: buyer@gmail.com\r\n"
            "Subject: Updated pricing for RFQ\r\n"
            "Date: Mon, 02 Nov 2026 09:00:00 +0000\r\n"
            "\r\n"
            "Unit price SAR 3450"
        )
        msg = email.message_from_string(raw)
        sent = _sent_for_from(store, "saad.bn@webknot.in", msg)
        self.assertIsNotNone(sent)
        assert sent is not None
        self.assertEqual(sent["ref"], "QQ-0067:SUP-11632")

    def test_reply_routes_to_correct_job_when_same_sender(self) -> None:
        store = _MemStore()
        store.rows.extend(
            [
                {
                    "folder": "sent",
                    "recipient": "saad.bn@webknot.in",
                    "ref": "QQ-0067:SUP-11632",
                    "subject": "RFQ: 12 x Apple iPhone 16",
                    "sent_at": "2026-11-02T08:00:00+00:00",
                    "conversation_id": "conv-old",
                },
                {
                    "folder": "sent",
                    "recipient": "saad.bn@webknot.in",
                    "ref": "QQ-0072:SUP-11632",
                    "subject": "Request for quotation: 5 iPhone 15 for team use",
                    "sent_at": "2026-11-02T11:00:00+00:00",
                    "conversation_id": "conv-new",
                },
            ]
        )
        raw = (
            "From: saad.bn@webknot.in\r\n"
            "Subject: Re: Request for quotation: 5 iPhone 15 for team use\r\n"
            "Date: Mon, 02 Nov 2026 12:00:00 +0000\r\n"
            "\r\n"
            "Unit price SAR 3200"
        )
        msg = email.message_from_string(raw)
        sent = _sent_for_from(store, "saad.bn@webknot.in", msg, instance_id="QQ-0072")
        self.assertIsNotNone(sent)
        assert sent is not None
        self.assertEqual(sent["ref"], "QQ-0072:SUP-11632")

    def test_skips_rfq_copy_in_sent_with_same_body(self) -> None:
        sent = {"subject": "RFQ: 5× iPhone 15 for team use", "body": "Please quote..."}
        msg = email.message_from_string(
            "Subject: RFQ: 5× iPhone 15 for team use\r\n\r\nPlease quote..."
        )
        self.assertTrue(_skip_as_outbound_echo(msg, sent))

    def test_does_not_skip_quote_when_subject_matches_rfq_only(self) -> None:
        sent = {
            "subject": "RFQ – 1 iPhone 17 Pro Max 528 GB",
            "body": "Please provide your quotation for the items below.",
        }
        msg = email.message_from_string(
            "Subject: RFQ – 1 iPhone 17 Pro Max 528 GB\r\n\r\n"
            "Unit price: SAR 6,450.00\nTotal price (1 unit): SAR 6,450.00"
        )
        self.assertFalse(_skip_as_outbound_echo(msg, sent))

    def test_subjects_match_across_en_dash_and_hyphen(self) -> None:
        self.assertTrue(
            _subjects_match(
                "Re: RFQ - Order 1 iPhone 15 128 GB Black",
                "RFQ – Order 1 iPhone 15 128 GB Black",
            )
        )

    def test_pick_sent_row_by_supplier_tag_in_subject(self) -> None:
        hits = [
            {"ref": "QQ-0092:SUP-11632", "subject": "RFQ x"},
            {"ref": "QQ-0092:SUP-11581", "subject": "RFQ x"},
        ]
        picked = _pick_sent_row("Re: RFQ x [SUP-11581]", hits)
        self.assertEqual(picked["ref"], "QQ-0092:SUP-11581")

    def test_pick_sent_row_ambiguous_without_supplier_tag(self) -> None:
        hits = [
            {"ref": "QQ-0092:SUP-11632", "subject": "RFQ x"},
            {"ref": "QQ-0092:SUP-11581", "subject": "RFQ x"},
        ]
        self.assertIsNone(_pick_sent_row("Re: RFQ x", hits))

    def test_dedupe_key_differs_when_body_changes(self) -> None:
        msg = email.message_from_string("Subject: Re: RFQ\r\n\r\n")
        k1 = _imap_dedupe_key(msg, "first body")
        k2 = _imap_dedupe_key(msg, "corrected unit price")
        self.assertNotEqual(k1, k2)


if __name__ == "__main__":
    unittest.main()
