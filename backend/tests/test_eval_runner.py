"""Unit tests for the M1 structural eval runner."""

from __future__ import annotations

import unittest

from aos.evals.runner import run_suite
from aos.kernel.settings import REPO

PACK = REPO / "packs" / "procurement_demo"


class EvalRunnerTests(unittest.TestCase):
    def test_refusals_structural_and_deferred(self) -> None:
        from aos.registry.loader import load_pack

        loaded = load_pack(PACK)
        suite = loaded.get("EvalSuite")["refusals"]
        defs = {kind: {name: obj.model_dump() for name, obj in objs.items()} for kind, objs in loaded.objects.items()}
        result = run_suite(
            suite_name="refusals",
            suite_spec=suite.model_dump(),
            defs=defs,
            pack_root=PACK,
        )
        self.assertEqual(result.status, "passed")
        self.assertEqual(result.detail["deferred_count"], 2)
        self.assertTrue(all(e["status"] == "deferred" for e in result.detail["expectations"]))
        self.assertGreater(result.total, 0)
        self.assertEqual(result.passed, result.total)

    def test_dry_run_script_resolves(self) -> None:
        from aos.registry.loader import load_pack

        loaded = load_pack(PACK)
        suite = loaded.get("EvalSuite")["dry_run"]
        defs = {kind: {name: obj.model_dump() for name, obj in objs.items()} for kind, objs in loaded.objects.items()}
        loaded = load_pack(PACK)
        result = run_suite(
            suite_name="dry_run",
            suite_spec=suite.model_dump(),
            defs=defs,
            pack_root=PACK,
            suite_file="evals/dry_run.yaml",
            pinned_digest=loaded.digest,
        )
        self.assertEqual(result.status, "passed")
        self.assertEqual(result.passed, 1)
        self.assertEqual(result.total, 1)
        self.assertEqual(result.detail["deferred_count"], 2)

    def test_dry_run_digest_mismatch(self) -> None:
        from aos.registry.loader import load_pack

        loaded = load_pack(PACK)
        suite = loaded.get("EvalSuite")["dry_run"]
        defs = {kind: {name: obj.model_dump() for name, obj in objs.items()} for kind, objs in loaded.objects.items()}
        result = run_suite(
            suite_name="dry_run",
            suite_spec=suite.model_dump(),
            defs=defs,
            pack_root=PACK,
            suite_file="evals/dry_run.yaml",
            pinned_digest="0" * 64,
        )
        self.assertEqual(result.status, "failed")
        check = result.detail["checks"][0]
        self.assertIn("published version", check["detail"])


if __name__ == "__main__":
    unittest.main()
