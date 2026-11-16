"""Worker protocol error types (must behave as normal exceptions)."""

from __future__ import annotations

import unittest

from aos.worker.errors import ValidationFailed


class WorkerErrorsTests(unittest.TestCase):
    def test_validation_failed_carries_errors_and_chains(self) -> None:
        err = ValidationFailed(
            "validation_failed",
            422,
            "Draft content is invalid",
            "Fix the fields and try again.",
            errors=[{"pointer": "/title", "message": "required"}],
        )
        self.assertEqual(len(err.errors or []), 1)
        try:
            try:
                raise ValueError("inner")
            except ValueError as inner:
                raise err from inner
        except ValidationFailed as caught:
            self.assertIsNotNone(caught.__cause__)
            self.assertIsInstance(caught.__cause__, ValueError)


if __name__ == "__main__":
    unittest.main()
