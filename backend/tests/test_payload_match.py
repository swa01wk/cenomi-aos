"""Rule verifier payload_match."""

from __future__ import annotations

import unittest

from aos.verifiers.payload_match import verify


class PayloadMatchTests(unittest.TestCase):
    def test_pass_when_erp_matches_payload(self) -> None:
        verdict, findings = verify(
            {
                "outputs": [
                    {
                        "artifact_type": "po_payload",
                        "content": {
                            "supplier_id": "SUP-11632",
                            "reference": "AOS-QQ-0092-PO1",
                            "need_by": "2026-12-20",
                            "po_amount": 3450,
                            "lines": [{"item": "iPhone", "quantity": 1, "unit_price": 3450}],
                        },
                    }
                ],
                "tool_receipts": [
                    {
                        "tool": "create_po",
                        "content": {
                            "id": "PO-1",
                            "supplier_id": "SUP-11632",
                            "reference": "AOS-QQ-0092-PO1",
                            "need_by": "2026-12-20",
                            "total": "3450",
                            "lines": [{"item": "iPhone", "quantity": 1, "unit_price": 3450}],
                        },
                    }
                ],
            }
        )
        self.assertEqual(verdict, "PASS")
        self.assertEqual(findings, [])

    def test_rework_without_erp_readback(self) -> None:
        verdict, _ = verify(
            {
                "outputs": [{"artifact_type": "po_payload", "content": {"supplier_id": "SUP-1", "lines": []}}],
                "tool_receipts": [],
            }
        )
        self.assertEqual(verdict, "REWORK")


if __name__ == "__main__":
    unittest.main()
