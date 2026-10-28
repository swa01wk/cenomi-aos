"""Unit tests for aos.verifiers.sources_cited."""

from __future__ import annotations

import unittest

from aos.verifiers import sources_cited


def _receipt(tool: str, ref: str, content: dict) -> dict:
    return {"tool": tool, "receipt_ref": ref, "content": content, "attempt_n": 1}


def _row(sid: str, rank: int, score: float, sources: list) -> dict:
    return {
        "rank": rank,
        "supplier": sid,
        "supplier_id": sid,
        "score": score,
        "sources": sources,
    }


def _inp(rows: list, receipts: list | None = None) -> dict:
    return {
        "outputs": [{"artifact_type": "supplier_list", "content": {"rows": rows}}],
        "tool_receipts": receipts or [],
        "artifact_types": {"supplier_list": {"row_key": "supplier_id"}},
    }


class SourcesCitedVerifierTests(unittest.TestCase):
    def test_passes_valid_list(self) -> None:
        ref = "tp_search"
        receipts = [
            _receipt(
                "search_suppliers",
                ref,
                {"items": [{"id": "SUP-1", "name": "A"}]},
            )
        ]
        rows = [_row("SUP-1", 1, 90.0, [ref])]
        verdict, findings = sources_cited.verify(_inp(rows, receipts))
        self.assertEqual(verdict, "PASS")
        self.assertEqual(findings, [])

    def test_missing_source(self) -> None:
        verdict, findings = sources_cited.verify(_inp([_row("SUP-1", 1, 90.0, [])]))
        self.assertEqual(verdict, "REWORK")
        self.assertTrue(any("no sources" in f for f in findings))

    def test_source_from_other_task_not_allowed(self) -> None:
        rows = [_row("SUP-1", 1, 90.0, ["tp_foreign"])]
        verdict, findings = sources_cited.verify(_inp(rows, []))
        self.assertEqual(verdict, "REWORK")
        self.assertTrue(any("not from this task" in f for f in findings))

    def test_supplier_not_in_search_receipt(self) -> None:
        ref = "tp_search"
        receipts = [_receipt("search_suppliers", ref, {"items": [{"id": "SUP-OTHER"}]})]
        rows = [_row("SUP-1", 1, 90.0, [ref])]
        verdict, findings = sources_cited.verify(_inp(rows, receipts))
        self.assertEqual(verdict, "REWORK")
        self.assertTrue(any("search_suppliers" in f for f in findings))

    def test_rank_gaps_and_wrong_score_order(self) -> None:
        ref = "tp_search"
        receipts = [
            _receipt(
                "search_suppliers",
                ref,
                {"items": [{"id": "A"}, {"id": "B"}]},
            )
        ]
        rows = [
            _row("A", 1, 50.0, [ref]),
            _row("B", 3, 90.0, [ref]),
        ]
        verdict, findings = sources_cited.verify(_inp(rows, receipts))
        self.assertEqual(verdict, "REWORK")
        self.assertTrue(any("rank:" in f for f in findings))

        rows2 = [
            _row("A", 1, 50.0, [ref]),
            _row("B", 2, 90.0, [ref]),
        ]
        verdict2, findings2 = sources_cited.verify(_inp(rows2, receipts))
        self.assertEqual(verdict2, "REWORK")
        self.assertTrue(any("score descending" in f for f in findings2))

    def test_findings_use_row_key_not_content(self) -> None:
        verdict, findings = sources_cited.verify(_inp([_row("SUP-SECRET", 1, 90.0, [])]))
        self.assertEqual(verdict, "REWORK")
        joined = " ".join(findings)
        self.assertIn("SUP-SECRET", joined)
        self.assertNotIn("SECRET", joined.replace("SUP-SECRET", ""))


if __name__ == "__main__":
    unittest.main()
