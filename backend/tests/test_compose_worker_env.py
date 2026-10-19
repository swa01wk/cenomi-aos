"""Compose worker service: no session secret or kernel database; the model settings come from .env."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]


class ComposeWorkerEnvTests(unittest.TestCase):
    def test_worker_service_has_no_session_secret(self) -> None:
        doc = yaml.safe_load((REPO / "deploy" / "docker-compose.yml").read_text())
        worker = doc["services"].get("worker")
        self.assertIsNotNone(worker, "worker service should be defined")
        env = worker.get("environment") or {}
        if isinstance(env, list):
            keys = {e.split("=")[0] for e in env if isinstance(e, str) and "=" in e}
        else:
            keys = set(env.keys())
        self.assertNotIn("AOS_SESSION_SECRET", keys)
        self.assertNotIn("AOS_DATABASE_URL", keys)
        self.assertNotIn("env_file", worker)
        ckpt = env.get("AOS_CHECKPOINT_DATABASE_URL") if isinstance(env, dict) else None
        self.assertIsNotNone(ckpt, "worker needs AOS_CHECKPOINT_DATABASE_URL")
        self.assertIn("aos_worker:", str(ckpt))

    def test_worker_takes_runtime_and_model_settings_from_env(self) -> None:
        env = yaml.safe_load((REPO / "deploy" / "docker-compose.yml").read_text())["services"]["worker"]["environment"]
        # Defaults keep CI and a plain `make up` on the scripted model.
        self.assertEqual(env["AOS_RUNTIME"], "${AOS_RUNTIME:-fake}")
        for key in (
            "AOS_MODEL_PROVIDER",
            "OPENAI_API_KEY",
            "OPENAI_MODEL",
            "AOS_MODEL_PRICE_IN_PER_MTOK",
            "AOS_MODEL_PRICE_OUT_PER_MTOK",
        ):
            self.assertIn(key, env)
            self.assertTrue(str(env[key]).startswith("${" + key), key)
