"""Demo mock fill for RFP supplier replies."""

from __future__ import annotations

import unittest

from aos.connectors.demo_proposal_fill import (
    build_demo_proposal_content,
    build_demo_question_content,
    is_agent_placeholder_proposal,
)


class DemoProposalFillTests(unittest.TestCase):
    def test_ack_from_any_email(self) -> None:
        body = "Thanks, we got it."
        content = build_demo_proposal_content("SUP-11564", body, received_at="2026-11-03T12:00:00Z")
        self.assertEqual(content["reply_kind"], "ack")
        self.assertIn("Thanks", content["reply_excerpt"])
        self.assertEqual(content["total"], 0)
        self.assertEqual(content["supplier"], "Rawabi Digital Services")

    def test_question_includes_cm_draft(self) -> None:
        body = "Is Salesforce integration in scope?"
        content = build_demo_proposal_content("SUP-11836", body, received_at="2026-11-03T12:00:00Z")
        self.assertEqual(content["reply_kind"], "question")
        self.assertIn("category manager", content["notes"].lower())

    def test_proposal_has_mock_pricing(self) -> None:
        body = "Our total is SAR 4,850,000 for the full redesign."
        content = build_demo_proposal_content("SUP-11564", body, received_at="2026-11-03T12:00:00Z")
        self.assertEqual(content["reply_kind"], "proposal")
        self.assertEqual(content["total"], 4_850_000)

    def test_technical_question_routes_to_category_manager(self) -> None:
        content = build_demo_question_content("SUP-11836", 1, received_at="2026-11-03T12:00:00Z")
        self.assertEqual(content["reply_kind"], "question")
        self.assertEqual(content["question_lane"], "technical")
        self.assertIn("category manager", content["notes"].lower())

    def test_commercial_question_routes_to_procurement(self) -> None:
        content = build_demo_question_content("SUP-11836", 2, received_at="2026-11-03T12:00:00Z")
        self.assertEqual(content["question_lane"], "commercial")
        self.assertIn("SLA", content["reply_excerpt"])
        self.assertIn("procurement", content["notes"].lower())

    def test_detects_truncated_placeholder(self) -> None:
        bad = {
            "reply_excerpt": "Supplier reply received, but conversation thread content is truncated",
            "total": 0,
        }
        self.assertTrue(is_agent_placeholder_proposal(bad))


if __name__ == "__main__":
    unittest.main()
