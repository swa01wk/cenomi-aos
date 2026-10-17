"""Compose worker service must not receive the session secret."""

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
        self.assertNotIn("env_file", worker)
