"""Failure class enums loaded from contract JSON schemas."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from .paths import schema_dir


def _load_json(name: str) -> dict[str, Any]:
    return json.loads((schema_dir() / name).read_text())


@lru_cache(maxsize=1)
def fail_attempt_classes() -> frozenset[str]:
    doc = _load_json("fail-attempt.schema.json")
    props = doc["properties"]["failure_class"]["allOf"]
    for part in props:
        if "enum" in part:
            return frozenset(str(v) for v in part["enum"])
    raise RuntimeError("fail-attempt.schema.json: failure_class subset enum not found")
