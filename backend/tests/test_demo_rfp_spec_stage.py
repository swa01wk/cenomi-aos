"""Specification-stage demo content."""

from __future__ import annotations

import unittest

from aos.connectors.demo_eval_rubrics import (
    OVERALL_COMMERCIAL_WEIGHT,
    OVERALL_TECHNICAL_WEIGHT,
)
from aos.connectors.demo_rfp_spec_stage import (
    build_procurement_validation_rows,
    build_scoring_method_agreement,
    build_template_compliance_rows,
)


class DemoRfpSpecStageTests(unittest.TestCase):
    def test_validation_covers_procurement_conditions(self) -> None:
        areas = {r["area"].lower() for r in build_procurement_validation_rows()}
        self.assertTrue(any("bill" in a for a in areas))
        self.assertTrue(any("contract" in a for a in areas))
        self.assertTrue(any("sla" in a for a in areas))
        self.assertTrue(any("scope" in a for a in areas))
        self.assertTrue(any("fixed" in a for a in areas))

    def test_scoring_agreement_matches_prd_weights(self) -> None:
        agree = build_scoring_method_agreement()
        self.assertAlmostEqual(agree["agreed_technical_weight"], OVERALL_TECHNICAL_WEIGHT)
        self.assertAlmostEqual(agree["agreed_commercial_weight"], OVERALL_COMMERCIAL_WEIGHT)
        self.assertIn("2 rounds", agree["approval_rounds_config"])

    def test_template_rows_include_upload_narrative(self) -> None:
        rows = build_template_compliance_rows()
        statuses = {r["status"] for r in rows}
        self.assertIn("user_added", statuses)


if __name__ == "__main__":
    unittest.main()
