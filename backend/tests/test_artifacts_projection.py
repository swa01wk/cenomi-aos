"""Unit tests for artifact visibility projection (M1-BE-04 C)."""

from __future__ import annotations

import unittest
import yaml

from aos.kernel.artifacts import VersionRecord, build_artifact_view, project
from aos.kernel.contracts import _canonical_json
from aos.registry.kinds import ArtifactType
from aos.kernel.settings import REPO

PACK = REPO / "packs" / "procurement_demo" / "artifact_types"
PLANT_PRICE = "SAR 88888.01"


def _load_type(name: str):
    doc = yaml.safe_load((PACK / f"{name}.yaml").read_text())
    return ArtifactType.model_validate(doc).spec


class ArtifactsProjectionTests(unittest.TestCase):
    def test_comparison_requester_hides_prices(self) -> None:
        spec = _load_type("comparison")
        content = {
            "rows": [
                {
                    "rank": 1,
                    "supplier": "Najd Supplies",
                    "unit_price": PLANT_PRICE,
                    "total": PLANT_PRICE,
                    "lead_time_days": 14,
                    "score": 88.0,
                }
            ]
        }
        full_hash = __import__("hashlib").sha256(_canonical_json(content)).hexdigest()
        rec = VersionRecord(
            artifact_id="art_test",
            artifact_type="comparison",
            version=1,
            status="draft",
            content=content,
            content_hash=full_hash,
            produced_by_kind="person",
            produced_by="noura",
            inputs=[],
            sources=[],
            verification=None,
            created_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        )
        out = project(rec, spec, ["requester"])
        self.assertIn("unit_price", out["hidden_fields"])
        self.assertIn("total", out["hidden_fields"])
        self.assertNotIn(PLANT_PRICE, __import__("json").dumps(out))
        self.assertNotIn("content_hash", out)
        self.assertIn("projected_content_hash", out)
        view = build_artifact_view(spec, {"rank", "supplier", "lead_time_days", "score"})
        self.assertNotIn("unit_price", view.get("columns", []))

    def test_comparison_buyer_sees_prices(self) -> None:
        spec = _load_type("comparison")
        content = {"rows": [{"rank": 1, "supplier": "A", "unit_price": PLANT_PRICE, "total": PLANT_PRICE, "score": 1}]}
        full_hash = __import__("hashlib").sha256(_canonical_json(content)).hexdigest()
        rec = VersionRecord(
            artifact_id="art_test",
            artifact_type="comparison",
            version=1,
            status="draft",
            content=content,
            content_hash=full_hash,
            produced_by_kind="person",
            produced_by="noura",
            inputs=[],
            sources=[],
            verification=None,
            created_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        )
        out = project(rec, spec, ["buyer"])
        self.assertEqual(out["hidden_fields"], [])
        self.assertIn(PLANT_PRICE, out["content"]["rows"][0]["unit_price"])
        self.assertEqual(out["content_hash"], full_hash)
        self.assertNotIn("projected_content_hash", out)

    def test_verification_findings_stripped_when_redacting(self) -> None:
        spec = _load_type("comparison")
        content = {"rows": [{"rank": 1, "supplier": "A", "unit_price": PLANT_PRICE, "total": PLANT_PRICE, "score": 1}]}
        rec = VersionRecord(
            artifact_id="art_test",
            artifact_type="comparison",
            version=1,
            status="draft",
            content=content,
            content_hash="abc",
            produced_by_kind="person",
            produced_by="noura",
            inputs=[{"artifact_id": "art_x", "version": 1, "content_hash": "dead", "excerpt": PLANT_PRICE}],
            sources=[{"source_ref": "mail:1", "label": "Quote", "body": PLANT_PRICE}],
            verification={
                "verifier": "price_check",
                "verdict": "PASS",
                "findings": [f"Unit price matches {PLANT_PRICE}"],
            },
            created_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        )
        out = project(rec, spec, ["requester"])
        dumped = __import__("json").dumps(out)
        self.assertNotIn(PLANT_PRICE, dumped)
        self.assertEqual(out["verification"], {"verifier": "price_check", "verdict": "PASS"})
        self.assertNotIn("excerpt", dumped)
        self.assertNotIn("body", dumped)

    def test_classification_ceiling_shareable_drops_budget_guidance(self) -> None:
        spec = _load_type("brief")
        content = {
            "title": "Trolleys",
            "category": "janitorial_equipment",
            "quantity": 40,
            "specification": "Fleet spec",
            "delivery_date": "2026-11-20",
            "delivery_site": "Mall A",
            "budget_guidance": "SAR 50000",
        }
        rec = VersionRecord(
            artifact_id="art_brief",
            artifact_type="brief",
            version=1,
            status="draft",
            content=content,
            content_hash="x",
            produced_by_kind="person",
            produced_by="faisal",
            inputs=[],
            sources=[],
            verification=None,
            created_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        )
        out = project(rec, spec, ["requester"], classification_ceiling="shareable")
        self.assertIn("budget_guidance", out["hidden_fields"])
        self.assertNotIn("budget_guidance", out["content"])


if __name__ == "__main__":
    unittest.main()
