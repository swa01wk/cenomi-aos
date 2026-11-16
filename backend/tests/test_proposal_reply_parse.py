"""RFP reply classification (ack before full proposal)."""

from __future__ import annotations

import unittest

from aos.connectors.proposal_reply_parse import classify_rfp_reply, parse_proposal_reply_text


class ProposalReplyParseTests(unittest.TestCase):
    def test_confirm_receipt_is_ack(self) -> None:
        body = (
            "Dear Noura,\n\nWe confirm receipt of the RFP invitation and intend to submit our proposal "
            "within five days.\n\nBest regards,\nRawabi"
        )
        self.assertEqual(classify_rfp_reply(body), "ack")
        parsed = parse_proposal_reply_text(body)
        self.assertEqual(parsed["reply_kind"], "ack")
        self.assertTrue(parsed["acknowledged"])

    def test_full_commercials_is_proposal(self) -> None:
        body = "Total project price: SAR 4,850,000\nLead time: 300 days"
        self.assertEqual(classify_rfp_reply(body), "proposal")

    def test_clarification_is_question(self) -> None:
        body = "Could you confirm whether integration with Salesforce is in scope?"
        self.assertEqual(classify_rfp_reply(body), "question")


if __name__ == "__main__":
    unittest.main()
