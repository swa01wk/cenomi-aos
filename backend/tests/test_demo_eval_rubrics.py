"""Demo eval rubrics align with PRD QCBS (70/30, five technical criteria)."""

from __future__ import annotations

import unittest

from aos.connectors.demo_eval_rubrics import (
    MIN_TECHNICAL_SCORE,
    OVERALL_COMMERCIAL_WEIGHT,
    OVERALL_TECHNICAL_WEIGHT,
    TECHNICAL_CRITERIA_RFP,
    commercial_envelope_score,
    rfp_rubric_bundle,
    technical_score_from_criteria,
)


class DemoEvalRubricsTests(unittest.TestCase):
    def test_prd_weights(self) -> None:
        self.assertAlmostEqual(OVERALL_TECHNICAL_WEIGHT, 0.70)
        self.assertAlmostEqual(OVERALL_COMMERCIAL_WEIGHT, 0.30)
        self.assertEqual(MIN_TECHNICAL_SCORE, 70.0)
        self.assertEqual(sum(w for _, _, w in TECHNICAL_CRITERIA_RFP), 100.0)

    def test_technical_criteria_cover_prd_names(self) -> None:
        labels = {label for _, label, _ in TECHNICAL_CRITERIA_RFP}
        self.assertIn("Scope understanding and methodology", labels)
        self.assertIn("Experience and references", labels)

    def test_rfp_bundle_scores_reconcile(self) -> None:
        sids = ["SUP-11836", "SUP-11564", "SUP-12448"]
        names = {s: s for s in sids}
        totals = {s: 4_000_000 + i * 100_000 for i, s in enumerate(sids)}
        tech_rows, comm_rows, _, tech_scores = rfp_rubric_bundle(sids, names, totals)
        self.assertGreaterEqual(len(tech_rows), 15)
        for sid in sids:
            summed = sum(
                float(r["contribution_pts"])
                for r in tech_rows
                if r["supplier_id"] == sid
            )
            self.assertAlmostEqual(summed, tech_scores[sid], places=1)
            c_env = commercial_envelope_score(comm_rows, sid)
            self.assertGreater(c_env, 0)


if __name__ == "__main__":
    unittest.main()
