"""Worker TypedDict keys match OpenAPI / JSON Schema."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import yaml

from aos.worker.types import AgentResult, WorkerAttempt

REPO = Path(__file__).resolve().parents[2]
CONTRACTS = REPO / "docs" / "specs" / "contracts"


class WorkerTypesTests(unittest.TestCase):
    def test_worker_attempt_required_keys(self) -> None:
        doc = yaml.safe_load((CONTRACTS / "openapi.yaml").read_text())
        required = set(doc["components"]["schemas"]["WorkerAttempt"]["required"])
        hints = set(WorkerAttempt.__required_keys__)  # type: ignore[attr-defined]
        self.assertEqual(hints, required)

    def test_agent_result_required_keys(self) -> None:
        schema = json.loads((CONTRACTS / "schemas" / "agent-result.schema.json").read_text())
        required = set(schema["required"])
        hints = set(AgentResult.__required_keys__)  # type: ignore[attr-defined]
        self.assertEqual(hints, required)
