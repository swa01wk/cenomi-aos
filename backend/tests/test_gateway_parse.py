"""Tool results: JSON text is parsed, plain text stays text (a result starting with 'n' used to raise)."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from aos.gateway.gateway import _parse_tool_result


def _result(text: str, *, is_error: bool = False) -> SimpleNamespace:
    return SimpleNamespace(is_error=is_error, content=[SimpleNamespace(text=text)])


class ParseToolResultTests(unittest.TestCase):
    def test_json_is_parsed(self) -> None:
        self.assertEqual(_parse_tool_result(_result('{"items": [1, 2]}')), {"items": [1, 2]})
        self.assertEqual(_parse_tool_result(_result("[1, 2]")), [1, 2])
        self.assertEqual(_parse_tool_result(_result('"quoted"')), "quoted")
        self.assertIsNone(_parse_tool_result(_result("null")))

    def test_plain_text_stays_text(self) -> None:
        for text in ("No matching categories", "none found", "Not available today", "nothing"):
            self.assertEqual(_parse_tool_result(_result(text)), text)

    def test_broken_json_stays_text(self) -> None:
        self.assertEqual(_parse_tool_result(_result("{not json")), "{not json")

    def test_tool_error_raises(self) -> None:
        with self.assertRaises(RuntimeError):
            _parse_tool_result(_result("boom", is_error=True))

    def test_empty(self) -> None:
        self.assertIsNone(_parse_tool_result(None))
        self.assertIsNone(_parse_tool_result(SimpleNamespace(is_error=False, content=[])))


if __name__ == "__main__":
    unittest.main()
