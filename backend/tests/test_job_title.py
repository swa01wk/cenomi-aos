"""Job title derivation from chat."""

from __future__ import annotations

import unittest

from aos.kernel.job_title import derive_job_title

HINTS = ["laptop", "need", "purchase", "equipment", "order"]


class JobTitleTests(unittest.TestCase):
    def test_handoff_blob_picks_request_line(self) -> None:
        blob = (
            "I need to purchase 20 laptops · naah nothing like that · no · just a general stock · under 150 USD"
        )
        title = derive_job_title(blob, hints=HINTS)
        self.assertIn("20 laptop", title.lower())

    def test_skips_greeting_only(self) -> None:
        self.assertEqual(derive_job_title("hey", hints=HINTS).lower(), "hey")

    def test_uses_brief_style_line(self) -> None:
        title = derive_job_title("We need 20 MacBook M4 laptops for the coding team", hints=HINTS)
        self.assertIn("MacBook", title)


if __name__ == "__main__":
    unittest.main()
