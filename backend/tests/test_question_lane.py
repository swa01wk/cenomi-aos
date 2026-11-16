"""Vendor clarification routing (commercial vs technical)."""

from __future__ import annotations

import unittest

from aos.connectors.demo_proposal_fill import classify_question_lane


class QuestionLaneTests(unittest.TestCase):
    def test_payment_is_commercial(self) -> None:
        self.assertEqual(classify_question_lane("Can you confirm net-30 payment terms?"), "commercial")

    def test_architecture_is_technical(self) -> None:
        self.assertEqual(
            classify_question_lane("Should the REST API follow OpenAPI 3.1 behind our gateway?"),
            "technical",
        )


if __name__ == "__main__":
    unittest.main()
