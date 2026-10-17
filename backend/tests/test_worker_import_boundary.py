"""Worker process must not import kernel, api, or psycopg."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


class WorkerImportBoundaryTests(unittest.TestCase):
    def test_worker_subprocess_has_no_forbidden_modules(self) -> None:
        script = """
import sys
import aos.worker.__main__  # noqa: F401
bad = {m for m in sys.modules if m.startswith(("aos.kernel", "aos.api", "psycopg"))}
if bad:
    raise SystemExit("forbidden: " + ", ".join(sorted(bad)))
"""
        env = dict(__import__("os").environ)
        env["PYTHONPATH"] = f"{REPO / 'backend' / 'src'}:{REPO / 'backend' / '.vendor'}"
        proc = subprocess.run(
            [sys.executable, "-c", script],
            cwd=REPO / "backend",
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
