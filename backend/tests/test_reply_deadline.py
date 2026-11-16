"""Vendor reply deadline parsing for demo/testing."""

import unittest

from aos.kernel.reply_deadline import (
    DEFAULT_DEMO_REPLY_MINUTES,
    demo_reply_timer_duration,
    parse_demo_reply_minutes,
)


class TestParseDemoReplyMinutes(unittest.TestCase):
    def test_default_when_empty(self) -> None:
        self.assertEqual(parse_demo_reply_minutes(None), DEFAULT_DEMO_REPLY_MINUTES)
        self.assertEqual(parse_demo_reply_minutes(""), DEFAULT_DEMO_REPLY_MINUTES)

    def test_plain_number(self) -> None:
        self.assertEqual(parse_demo_reply_minutes("1.5"), 1.5)
        self.assertEqual(parse_demo_reply_minutes("2"), 2.0)

    def test_days_label_still_minutes_in_demo(self) -> None:
        self.assertEqual(parse_demo_reply_minutes("1.5 days"), 1.5)
        self.assertEqual(parse_demo_reply_minutes("2 days"), 2.0)

    def test_timer_duration_seconds(self) -> None:
        self.assertEqual(demo_reply_timer_duration(1.5), "90s")
        self.assertEqual(demo_reply_timer_duration(2), "120s")


class TestHealSupplierList(unittest.TestCase):
    def test_heal_zero_scores(self) -> None:
        from aos.verifiers.supplier_scoring import heal_supplier_list_content

        out = heal_supplier_list_content(
            {
                "rows": [
                    {
                        "rank": 1,
                        "supplier": "A",
                        "past_pos": 7,
                        "on_time_pct": 100.0,
                        "score": 0,
                        "points_asl": 20,
                        "points_history": 0,
                        "points_delivery": 0,
                    }
                ]
            }
        )
        row = out["rows"][0]
        self.assertEqual(row["points_history"], 35)
        self.assertEqual(row["points_delivery"], 30)
        self.assertEqual(row["score"], 85)
