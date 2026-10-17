"""Worker process configuration."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import jwt

from aos.worker.config import load_config

REPO = Path(__file__).resolve().parents[2]
_DEV = "aos-dev-session-secret-change-me-0123456789abcdef"


class WorkerConfigTests(unittest.TestCase):
    def test_aos_runtime_is_required(self) -> None:
        token = jwt.encode({"aud": "aos-worker", "sub": "worker-1"}, _DEV, algorithm="HS256")
        env = {k: v for k, v in os.environ.items() if k != "AOS_RUNTIME"}
        env["AOS_WORKER_TOKEN"] = token
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaisesRegex(RuntimeError, "AOS_RUNTIME"):
                load_config()

    def test_langgraph_runtime_exits_at_startup(self) -> None:
        script = """
import asyncio
import os
os.environ["AOS_RUNTIME"] = "langgraph"
os.environ["AOS_WORKER_TOKEN"] = %r
from aos.worker.__main__ import _main_async
try:
    asyncio.run(_main_async())
except SystemExit as e:
    raise SystemExit(e.code)
""" % jwt.encode({"aud": "aos-worker", "sub": "test-run"}, _DEV, algorithm="HS256")
        env = dict(os.environ)
        env["PYTHONPATH"] = f"{REPO / 'backend' / 'src'}:{REPO / 'backend' / '.vendor'}"
        proc = subprocess.run(
            [sys.executable, "-c", script],
            cwd=REPO / "backend",
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 1)
        self.assertIn("langgraph", proc.stderr.lower() + proc.stdout.lower())

    def test_aos_worker_lanes_must_be_known(self) -> None:
        token = jwt.encode({"aud": "aos-worker", "sub": "worker-1"}, _DEV, algorithm="HS256")
        env = {
            "AOS_WORKER_TOKEN": token,
            "AOS_RUNTIME": "fake",
            "AOS_WORKER_LANES": "assist,bogus",
        }
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaisesRegex(RuntimeError, "unknown lane"):
                load_config()

    def test_main_config_error_exits_without_traceback(self) -> None:
        script = """
import os
os.environ.pop("AOS_RUNTIME", None)
os.environ["AOS_WORKER_TOKEN"] = %r
from aos.worker.__main__ import main
main()
""" % jwt.encode({"aud": "aos-worker", "sub": "w1"}, _DEV, algorithm="HS256")
        env = dict(os.environ)
        env["PYTHONPATH"] = f"{REPO / 'backend' / 'src'}:{REPO / 'backend' / '.vendor'}"
        proc = subprocess.run(
            [sys.executable, "-c", script],
            cwd=REPO / "backend",
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 1)
        combined = proc.stderr + proc.stdout
        self.assertIn("AOS_RUNTIME", combined)
        self.assertNotIn("Traceback", combined)
