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
_CHECKPOINT_URL = (
    "postgresql://aos_worker:aos_worker_dev@127.0.0.1:5432/aos"
    "?options=-c%20search_path%3Dlg_checkpoints"
)


def _base_worker_env(**overrides: str) -> dict[str, str]:
    token = overrides.pop("AOS_WORKER_TOKEN", jwt.encode({"aud": "aos-worker", "sub": "worker-1"}, _DEV, algorithm="HS256"))
    env = {
        "AOS_WORKER_TOKEN": token,
        "AOS_RUNTIME": "fake",
        "AOS_CHECKPOINT_DATABASE_URL": _CHECKPOINT_URL,
    }
    env.update(overrides)
    return env


# A developer's .env may hold real-model settings (from `make model-real` or the gate). `make` exports them to the
# tests, and a worker subprocess that inherits them starts for real and polls forever instead of exiting.
_REAL_MODEL_ENV = {
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "AOS_MODEL_PRICE_IN_PER_MTOK",
    "AOS_MODEL_PRICE_OUT_PER_MTOK",
}


def _run_worker_script(script: str) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k not in _REAL_MODEL_ENV}
    env["AOS_MODEL_PROVIDER"] = "openai"
    env["PYTHONPATH"] = f"{REPO / 'backend' / 'src'}:{REPO / 'backend' / '.vendor'}"
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO / "backend",
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


class WorkerConfigTests(unittest.TestCase):
    def test_aos_runtime_is_required(self) -> None:
        env = _base_worker_env()
        env.pop("AOS_RUNTIME")
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaisesRegex(RuntimeError, "AOS_RUNTIME"):
                load_config()

    def test_checkpoint_url_required_and_aos_worker_role(self) -> None:
        with patch.dict(os.environ, _base_worker_env(), clear=True):
            cfg = load_config()
            self.assertIn("aos_worker", cfg.checkpoint_database_url)
        with patch.dict(os.environ, _base_worker_env(AOS_CHECKPOINT_DATABASE_URL=""), clear=True):
            with self.assertRaisesRegex(RuntimeError, "AOS_CHECKPOINT_DATABASE_URL"):
                load_config()
        bad = _CHECKPOINT_URL.replace("aos_worker", "aos_kernel")
        with patch.dict(os.environ, _base_worker_env(AOS_CHECKPOINT_DATABASE_URL=bad), clear=True):
            with self.assertRaisesRegex(RuntimeError, "aos_worker"):
                load_config()

    def test_langgraph_runtime_exits_at_startup(self) -> None:
        script = """
import asyncio
import os
os.environ["AOS_RUNTIME"] = "langgraph"
os.environ["AOS_WORKER_TOKEN"] = %r
os.environ["AOS_CHECKPOINT_DATABASE_URL"] = %r
from aos.worker.__main__ import _main_async
try:
    asyncio.run(_main_async())
except SystemExit as e:
    raise SystemExit(e.code)
""" % (
            jwt.encode({"aud": "aos-worker", "sub": "test-run"}, _DEV, algorithm="HS256"),
            _CHECKPOINT_URL,
        )
        proc = _run_worker_script(script)
        self.assertEqual(proc.returncode, 1)
        combined = (proc.stderr + proc.stdout).lower()
        self.assertTrue(
            "openai_api_key" in combined or "aos_model_price" in combined,
            combined,
        )

    def test_aos_worker_lanes_must_be_known(self) -> None:
        token = jwt.encode({"aud": "aos-worker", "sub": "worker-1"}, _DEV, algorithm="HS256")
        env = _base_worker_env(AOS_WORKER_TOKEN=token, AOS_WORKER_LANES="assist,bogus")
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
        proc = _run_worker_script(script)
        self.assertEqual(proc.returncode, 1)
        combined = proc.stderr + proc.stdout
        self.assertIn("AOS_RUNTIME", combined)
        self.assertNotIn("Traceback", combined)
