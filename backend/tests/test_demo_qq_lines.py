"""Quick Quote line-item comparison (demo)."""

from __future__ import annotations

import unittest

from aos.connectors.demo_qq_lines import (
    build_comparison_rows,
    build_line_matrix_rows,
    format_qq_line_comparison_chat_block,
    resolve_three_suppliers,
)


class DemoQqLinesTests(unittest.TestCase):
    def test_resolve_three_from_one_awarded(self) -> None:
        keys = resolve_three_suppliers(["SUP-11615"])
        self.assertEqual(len(keys), 3)
        self.assertEqual(keys[0], "SUP-11615")

    def test_matrix_has_three_vendors(self) -> None:
        keys = resolve_three_suppliers(["SUP-11615"])
        rows = build_line_matrix_rows(keys, quantity=1)
        self.assertGreaterEqual(len(rows), 4)
        block = format_qq_line_comparison_chat_block(keys)
        self.assertIn("Webknot", block)
        self.assertIn("Najd", block)

    def test_comparison_has_three_rows(self) -> None:
        keys = resolve_three_suppliers(["SUP-11615"])
        rows = build_comparison_rows(keys, quantity=1)
        self.assertEqual(len(rows), 3)


if __name__ == "__main__":
    unittest.main()
