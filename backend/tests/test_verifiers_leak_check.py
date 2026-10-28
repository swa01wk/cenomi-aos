"""Unit tests for aos.verifiers.leak_check."""

from __future__ import annotations

import json
import unittest

from aos.verifiers import leak_check


ARTIFACT_TYPES = {
    "brief": {
        "classification": "internal",
        "row_based": False,
        "fields": {"budget_guidance": {"classification": "internal"}},
    },
    "rfq_email": {
        "classification": "shareable",
        "row_based": False,
        "fields": {"body": {"classification": "shareable"}, "subject": {"classification": "shareable"}},
    },
}


def _inp(*, body: str, budget: int | str = 40000) -> dict:
    return {
        "outputs": [
            {
                "artifact_type": "rfq_email",
                "content": {"body": body, "subject": "RFQ", "supplier_id": "S1", "to": "a@b.c"},
            }
        ],
        "instance_artifacts": [
            {
                "artifact_type": "brief",
                "content": {"budget_guidance": budget, "title": "x"},
            }
        ],
        "artifact_types": ARTIFACT_TYPES,
    }


class LeakCheckVerifierTests(unittest.TestCase):
    def test_number_forms_match(self) -> None:
        for body in ("Price near 40,000 SAR", "Budget SAR 40000", "About 40k total"):
            verdict, _ = leak_check.verify(_inp(body=body))
            self.assertEqual(verdict, "REWORK", body)

    def test_140000_does_not_match_40000(self) -> None:
        verdict, findings = leak_check.verify(_inp(body="Total 140000 only"))
        self.assertEqual(verdict, "PASS")
        self.assertEqual(findings, [])

    def test_case_insensitive_text(self) -> None:
        verdict, _ = leak_check.verify(_inp(body="See INTERNALNOTE", budget="internalnote"))
        self.assertEqual(verdict, "REWORK")

    def test_short_values_ignored(self) -> None:
        verdict, findings = leak_check.verify(_inp(body="ok 99 fine", budget=99))
        self.assertEqual(verdict, "PASS")
        self.assertEqual(findings, [])

    def test_finding_names_fields_not_value(self) -> None:
        verdict, findings = leak_check.verify(_inp(body="Pay 40000 please"))
        self.assertEqual(verdict, "REWORK")
        joined = " ".join(findings)
        self.assertIn("body", joined)
        self.assertIn("budget_guidance", joined)
        self.assertNotIn("40000", joined)

    def test_stored_verification_shape_has_no_leaked_value(self) -> None:
        verdict, findings = leak_check.verify(_inp(body="SAR 40,000"))
        stored = {"verifier": "leak_check", "verdict": verdict, "findings": findings}
        blob = json.dumps(stored)
        self.assertNotIn("40000", blob)
        self.assertNotIn("40,000", blob)


if __name__ == "__main__":
    unittest.main()


class RealPackTypes(unittest.TestCase):
    """The pack's own classifications, not hand-written ones: an honest RFQ must pass."""

    @classmethod
    def setUpClass(cls) -> None:
        from pathlib import Path

        from aos.registry.loader import load_pack

        pack = load_pack(Path(__file__).resolve().parents[2] / "packs" / "procurement_demo")
        cls.types = {}
        for name, at in pack.get("ArtifactType").items():
            s = at.spec
            cls.types[name] = {
                "classification": s.classification,
                "row_based": s.row_based,
                "row_key": s.row_key,
                "fields": {
                    f: {"type": fs.type, "classification": fs.classification or s.classification}
                    for f, fs in s.fields.items()
                },
            }
        cls.brief = {
            "title": "Cleaning trolleys", "category": "CAT-0042", "quantity": 40,
            "specification": "Stainless steel, three shelves", "delivery_date": "2026-11-20",
            "delivery_site": "Mall A loading bay", "budget_guidance": 40000,
        }

    def _run(self, body: str):
        return leak_check.verify({
            "artifact_types": self.types,
            "outputs": [{"artifact_type": "rfq_email", "content": {
                "supplier_id": "S1", "to": "a@b.c", "subject": "RFQ: Cleaning trolleys", "body": body}}],
            "instance_artifacts": [{"artifact_type": "brief", "content": self.brief}],
        })

    def test_honest_rfq_passes(self) -> None:
        verdict, findings = self._run(
            "Please quote 40 Cleaning trolleys (Stainless steel, three shelves) for delivery to "
            "Mall A loading bay by 2026-11-20."
        )
        self.assertEqual((verdict, findings), ("PASS", []))

    def test_budget_in_rfq_is_caught(self) -> None:
        verdict, findings = self._run("Please quote 40 Cleaning trolleys; our budget is SAR 40,000.")
        self.assertEqual(verdict, "REWORK")
        self.assertEqual(findings, ["body: leaks brief.budget_guidance"])
