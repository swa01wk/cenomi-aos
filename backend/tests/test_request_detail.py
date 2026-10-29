"""Request-detail detection for conversation → intake."""

from __future__ import annotations

import unittest

from aos.kernel.instances import _text_from_turn_blocks
from aos.kernel.request_detail import message_indicates_request_detail


class RequestDetailTests(unittest.TestCase):
    def test_small_talk_is_not_detail(self) -> None:
        wf = {"spec": {"intake_hints": ["equipment", "need", "laptop"]}}
        self.assertFalse(message_indicates_request_detail("hi", wf))
        self.assertFalse(message_indicates_request_detail("hey how are you?", wf))

    def test_hint_match_is_detail(self) -> None:
        wf = {"spec": {"intake_hints": ["equipment", "need", "laptop"]}}
        self.assertTrue(message_indicates_request_detail("We need equipment for the site", wf))

    def test_text_from_turn_blocks(self) -> None:
        blocks = [{"kind": "text", "text": "Need 20 laptops"}]
        self.assertEqual(_text_from_turn_blocks(blocks), "Need 20 laptops")


if __name__ == "__main__":
    unittest.main()
