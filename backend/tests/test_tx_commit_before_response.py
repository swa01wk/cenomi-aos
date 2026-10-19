"""Writes commit before the response is sent, so a client's next read sees them."""

from __future__ import annotations

import typing
import unittest

from aos.api.deps import TxDep


class TxScopeTests(unittest.TestCase):
    def test_tx_dependency_commits_before_the_response(self) -> None:
        dep = typing.get_args(TxDep)[1]
        # FastAPI's default scope for yield dependencies runs the exit code (our commit) after the response is sent.
        self.assertEqual(getattr(dep, "scope", None), "function")


if __name__ == "__main__":
    unittest.main()
