"""Unit tests for aos.verifiers.brief_schema."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from aos.kernel import clock
from aos.verifiers import brief_schema


def _brief(**overrides: object) -> dict:
    base = {
        "title": "Trolleys",
        "category": "CAT-JAN-EQ",
        "quantity": 40,
        "specification": "Industrial",
        "delivery_date": "2026-12-01",
        "delivery_site": "Mall A",
    }
    base.update(overrides)
    return base


def _inp(**overrides: object) -> dict:
    doc = {
        "now": datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
        "outputs": [{"artifact_type": "brief", "content": _brief()}],
        "tool_receipts": [
            {
                "tool": "browse_categories",
                "receipt_ref": "tp_1",
                "content": {"items": [{"id": "CAT-JAN-EQ", "name": "Janitorial equipment"}]},
            }
        ],
        "artifact_types": {},
        "instance_artifacts": [],
    }
    doc.update(overrides)
    return doc


class BriefSchemaVerifierTests(unittest.TestCase):
    def test_passes_complete_brief(self) -> None:
        verdict, findings = brief_schema.verify(_inp())
        self.assertEqual(verdict, "PASS")
        self.assertEqual(findings, [])

    def test_one_finding_per_bad_field(self) -> None:
        content = _brief()
        content.pop("title")
        content["quantity"] = 0
        content["category"] = "CAT-UNKNOWN"
        content["delivery_date"] = "bad"
        verdict, findings = brief_schema.verify(
            _inp(outputs=[{"artifact_type": "brief", "content": content}])
        )
        self.assertEqual(verdict, "REWORK")
        self.assertGreaterEqual(len(findings), 4)
        joined = " ".join(findings)
        self.assertIn("title:", joined)
        self.assertIn("quantity:", joined)
        self.assertIn("category:", joined)
        self.assertIn("delivery_date:", joined)

    def test_delivery_date_boundary(self) -> None:
        now = datetime(2026, 6, 1, tzinfo=UTC)
        too_soon = (now.date() + timedelta(days=2)).isoformat()
        ok = (now.date() + timedelta(days=3)).isoformat()
        _, findings_bad = brief_schema.verify(
            _inp(
                now=now,
                outputs=[{"artifact_type": "brief", "content": _brief(delivery_date=too_soon)}],
            )
        )
        self.assertTrue(any("delivery_date" in f for f in findings_bad))
        verdict_ok, findings_ok = brief_schema.verify(
            _inp(
                now=now,
                outputs=[{"artifact_type": "brief", "content": _brief(delivery_date=ok)}],
            )
        )
        self.assertEqual(verdict_ok, "PASS")
        self.assertEqual(findings_ok, [])

    def test_invented_category_rework(self) -> None:
        verdict, findings = brief_schema.verify(
            _inp(outputs=[{"artifact_type": "brief", "content": _brief(category="CAT-0000")}])
        )
        self.assertEqual(verdict, "REWORK")
        self.assertTrue(any("category" in f for f in findings))

    def test_demo_clock_advances_delivery_rule(self) -> None:
        clock.configure(demo_enabled=True, offset_seconds=0)
        self.addCleanup(clock.configure, demo_enabled=False, offset_seconds=0)
        clock.set_frozen_wall(datetime(2026, 1, 1, tzinfo=UTC))
        self.addCleanup(clock.set_frozen_wall, None)
        clock.set_offset(86400 * 10)
        self.addCleanup(clock.set_offset, 0)
        advanced = clock.now().date()
        borderline = (advanced + timedelta(days=2)).isoformat()
        verdict, findings = brief_schema.verify(
            {
                "now": clock.now(),
                "outputs": [{"artifact_type": "brief", "content": _brief(delivery_date=borderline)}],
                "tool_receipts": _inp()["tool_receipts"],
                "artifact_types": {},
                "instance_artifacts": [],
            }
        )
        self.assertEqual(verdict, "REWORK")
        self.assertTrue(any("delivery_date" in f for f in findings))


if __name__ == "__main__":
    unittest.main()
