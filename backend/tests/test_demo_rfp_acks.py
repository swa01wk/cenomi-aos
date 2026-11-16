"""Staggered demo RFP supplier simulation timeline."""

from __future__ import annotations

import os
import unittest
from datetime import UTC, datetime

from aos.kernel import demo_rfp_acks


class DemoRfpAckScheduleTests(unittest.TestCase):
    def test_timeline_includes_ack_questions_proposal(self) -> None:
        os.environ["AOS_DEMO_RFP_ACK_FIRST_S"] = "20"
        os.environ["AOS_DEMO_RFP_ACK_STAGGER_S"] = "25"
        os.environ["AOS_DEMO_RFP_QUESTIONS_PER_VENDOR"] = "3"
        anchor = datetime(2026, 11, 3, 12, 0, 0, tzinfo=UTC)
        timeline = demo_rfp_acks.build_demo_rfp_timeline(
            ["SUP-12448", "SUP-11564"], anchor=anchor
        )
        kinds = [ev["kind"] for ev in timeline if ev["supplier"] == "SUP-11564"]
        self.assertEqual(kinds, ["ack", "question", "question", "question", "proposal"])
        ack = next(ev for ev in timeline if ev["id"] == "SUP-11564:ack")
        self.assertTrue(ack["at"].startswith("2026-11-03T12:00:20"))


if __name__ == "__main__":
    unittest.main()
