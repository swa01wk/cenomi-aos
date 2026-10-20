"""Runtime guard and condition expression evaluation (M2-BE-01 part 1)."""

from __future__ import annotations

import unittest
from decimal import Decimal
from pathlib import Path

from aos.registry.expressions import ExpressionError, evaluate
from aos.registry.loader import load_pack

REPO = Path(__file__).resolve().parents[2]
PACK = REPO / "packs" / "procurement_demo"


class EvaluateTriState(unittest.TestCase):
    def test_missing_ref_comparisons_and_logic(self) -> None:
        scope = {"attr": {}, "workflow": {}}
        self.assertFalse(evaluate("!(attr.missing == 1)", scope))
        self.assertFalse(evaluate('attr.missing != "PASS"', scope))
        self.assertFalse(evaluate("false && attr.missing == 1", scope))
        self.assertTrue(evaluate("attr.x == 1 || true", scope))

    def test_no_truthiness_at_top(self) -> None:
        scope = {"attr": {"n": 3}, "workflow": {}}
        self.assertFalse(evaluate("attr.n", scope))
        self.assertFalse(evaluate("3", scope))
        self.assertFalse(evaluate("1 + 2", scope))
        self.assertFalse(evaluate('size("abc")', scope))

    def test_operators_and_grouping(self) -> None:
        scope = {"attr": {"a": 5, "b": 2}}
        self.assertTrue(evaluate("attr.a >= 3 && attr.b < 5", scope))
        self.assertFalse(evaluate("attr.a > 10 || attr.b > 10", scope))
        self.assertTrue(evaluate("!(attr.a == 0)", scope))
        self.assertTrue(evaluate("(attr.a + attr.b) == 7", scope))

    def test_string_equality(self) -> None:
        scope = {"artifact": {"verification": {"leak_check": "PASS"}}}
        self.assertTrue(evaluate('artifact.verification.leak_check == "PASS"', scope))

    def test_compare_string_with_number_is_unknown(self) -> None:
        scope = {"artifact": {"po_amount": "25000"}}
        self.assertFalse(evaluate('artifact.po_amount > 25000', scope))

    def test_ordering_on_non_numbers_is_unknown(self) -> None:
        scope = {"artifact": {"verification": {"leak_check": "PASS"}}}
        self.assertFalse(evaluate('artifact.verification.leak_check > "A"', scope))

    def test_division_by_zero_is_unknown(self) -> None:
        scope = {"attr": {"a": 1, "b": 0}}
        self.assertFalse(evaluate("attr.a / attr.b == 1", scope))

    def test_decimal_and_int_compare_numerically(self) -> None:
        scope = {"artifact": {"po_amount": Decimal("25001")}}
        self.assertTrue(evaluate("artifact.po_amount > 25000", scope))
        scope2 = {"attr": {"x": Decimal("2.5")}}
        self.assertTrue(evaluate("attr.x == 2.5", scope2))

    def test_item_namespace_missing_is_unknown(self) -> None:
        scope: dict = {"attr": {}}
        self.assertFalse(evaluate("item.id == 1", scope))
        scope2 = {"attr": {}, "item": {}}
        self.assertFalse(evaluate("item.id == 1", scope2))

    def test_guard_functions(self) -> None:
        scope = {
            "workflow": {
                "reached": ["intake", "rfq_drafting"],
                "started_with": {"brief_version": 2},
            },
            "attr": {"brief_version": 2, "tags": ["a", "b"]},
        }
        self.assertTrue(evaluate('workflow.reached("rfq_drafting")', scope))
        self.assertTrue(evaluate("same(brief_version)", scope))
        self.assertTrue(evaluate("all(true, attr.brief_version == 2)", scope))
        self.assertTrue(evaluate("any(false, attr.brief_version == 2)", scope))
        self.assertTrue(evaluate("size(attr.tags) == 2", scope))

    def test_invalid_syntax_raises(self) -> None:
        scope = {"attr": {}}
        with self.assertRaises(ExpressionError):
            evaluate("", scope)
        with self.assertRaises(ExpressionError):
            evaluate("attr.a +", scope)
        with self.assertRaises(ExpressionError):
            evaluate("attr.a $ 1", scope)


class PolicyConditions(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        loaded = load_pack(PACK)
        cls.conditions: list[str] = []
        for pol in loaded.get("Policy").values():
            for rule in pol.spec.rules:
                cls.conditions.extend(rule.conditions)
                if rule.approval:
                    for step in rule.approval.chain:
                        if step.when:
                            cls.conditions.append(step.when)

    def test_quick_quote_gate_conditions(self) -> None:
        scopes = {
            'workflow.reached("rfq_drafting")': {
                "workflow": {"reached": ["rfq_drafting"]},
            },
            'artifact.verification.leak_check == "PASS"': {
                "artifact": {"verification": {"leak_check": "PASS"}},
            },
            'workflow.state == "ordering"': {
                "workflow": {"state": "ordering"},
            },
            "artifact.po_amount > 25000": {
                "artifact": {"po_amount": Decimal("30000")},
            },
        }
        for cond in self.conditions:
            scope = scopes.get(cond)
            if scope is None:
                continue
            self.assertTrue(evaluate(cond, scope), cond)


if __name__ == "__main__":
    unittest.main()
