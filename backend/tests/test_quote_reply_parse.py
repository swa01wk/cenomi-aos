"""Quote field extraction from supplier reply bodies."""

from __future__ import annotations

import email
import unittest

from aos.connectors.imap_inbound import _extract_body
from aos.connectors.quote_reply_parse import append_parse_hints, parse_quote_reply_text


class QuoteReplyParseTests(unittest.TestCase):
    def test_rawabi_style_reply(self) -> None:
        body = """
Unit price: SAR 5,750
Delivery: SAR 150
Total price (1 unit): SAR 5,900
Lead time: 3 days
"""
        parsed = parse_quote_reply_text(body)
        self.assertEqual(parsed["unit_price"], 5750.0)
        self.assertEqual(parsed["total"], 5900.0)
        self.assertEqual(parsed["lead_time_days"], 3)

    def test_append_hints_once(self) -> None:
        body = "Unit price: SAR 960\nTotal: SAR 38400\nLead time: 14 days\n"
        enriched = append_parse_hints(body, parse_quote_reply_text(body))
        self.assertEqual(enriched.count("auto-detected"), 1)
        self.assertIn("unit_price: 960", enriched)
        self.assertIn("lead_time_days: 14", enriched)

    def test_extract_html_only_email(self) -> None:
        raw = (
            "Content-Type: text/html; charset=utf-8\r\n\r\n"
            "<html><body><p>Unit price: <b>SAR 6,450.00</b></p>"
            "<p>Total price (1 unit): SAR 6,450.00</p>"
            "<p>Lead time: 5 days</p></body></html>"
        )
        msg = email.message_from_string(raw)
        text = _extract_body(msg)
        self.assertIn("6450", text.replace(",", ""))
        parsed = parse_quote_reply_text(text)
        self.assertEqual(parsed.get("unit_price"), 6450.0)
        self.assertEqual(parsed.get("lead_time_days"), 5)


if __name__ == "__main__":
    unittest.main()
