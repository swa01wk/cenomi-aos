"""Fake model scripts: relative dates stay valid whatever day the suite runs."""

from __future__ import annotations

import unittest
from datetime import date, datetime, timezone

from aos.verifiers import brief_schema
from aos.worker.scripts_loader import load_fake_script


class FakeScriptDateTests(unittest.TestCase):
    def test_relative_dates_expand_from_today(self) -> None:
        script = load_fake_script("request_intake.happy.yaml", attempt_n=2, today=date(2026, 11, 16))
        content = script.turns[0].tool_calls[0]["args"]["content"]
        self.assertEqual(content["delivery_date"], "2026-12-07")
        self.assertEqual(content["vendor_reply_deadline"], "2026-11-23")

    def test_happy_intake_brief_passes_brief_schema_today(self) -> None:
        script = load_fake_script("request_intake.happy.yaml", attempt_n=2)
        content = script.turns[0].tool_calls[0]["args"]["content"]
        verdict, findings = brief_schema.verify(
            {
                "now": datetime.now(timezone.utc),
                "outputs": [{"artifact_type": "brief", "content": content}],
                "tool_receipts": [{"tool": "browse_categories", "content": {"items": [{"id": "CAT-JAN-EQ"}]}}],
            }
        )
        self.assertEqual((verdict, findings), ("PASS", []))


if __name__ == "__main__":
    unittest.main()
