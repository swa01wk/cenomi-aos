"""Module-level RFP pricing and BAFO copy."""

from __future__ import annotations

import unittest

from aos.connectors.demo_rfp_modules import (
    build_bafo_email_body,
    build_module_matrix_rows,
    demo_proposal_pricing_modules,
    format_module_comparison_chat_block,
    format_proposal_modules_chat_summary,
    suppliers_with_bafo_outliers,
)


class DemoRfpModulesTests(unittest.TestCase):
    def test_module_totals_match_supplier_demo_totals(self) -> None:
        for sid, total in (
            ("SUP-11836", 4_620_000),
            ("SUP-11564", 4_850_000),
            ("SUP-12448", 4_990_000),
        ):
            mods = demo_proposal_pricing_modules(sid)
            self.assertEqual(sum(m["amount"] for m in mods), total)

    def test_matrix_has_talking_points(self) -> None:
        rows = build_module_matrix_rows()
        self.assertGreaterEqual(len(rows), 5)
        self.assertTrue(any("fair benchmark" in (r.get("bafo_talking_point") or "").lower() for r in rows))

    def test_bafo_body_challenges_outlier(self) -> None:
        body = build_bafo_email_body("SUP-12448")
        self.assertIn("MOD-04", body)
        self.assertIn("fair", body.lower())

    def test_outlier_suppliers_non_empty(self) -> None:
        self.assertIn("SUP-12448", suppliers_with_bafo_outliers())

    def test_chat_comparison_lists_three_vendors(self) -> None:
        block = format_module_comparison_chat_block()
        self.assertIn("Tamkeen", block)
        self.assertIn("Rawabi", block)
        self.assertIn("Peninsula", block)
        self.assertIn("MOD-03", block)
        self.assertIn("MOD-04", block)

    def test_chat_proposal_summary_has_modules(self) -> None:
        text = format_proposal_modules_chat_summary("SUP-11836")
        self.assertIn("MOD-01", text)
        self.assertIn("Tamkeen", text)


if __name__ == "__main__":
    unittest.main()
