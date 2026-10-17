"""Validate worker payloads against contract JSON Schemas."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from .paths import schema_dir


def _load_schemas() -> dict[str, dict[str, Any]]:
    root = schema_dir()
    return {p.name: json.loads(p.read_text()) for p in sorted(root.glob("*.schema.json"))}


@lru_cache(maxsize=1)
def _agent_result_validator() -> Draft202012Validator:
    schemas = _load_schemas()
    registry = Registry().with_resources(
        (s["$id"], Resource.from_contents(s)) for s in schemas.values()
    )
    return Draft202012Validator(schemas["agent-result.schema.json"], registry=registry)


def agent_result_valid(result: dict[str, Any]) -> bool:
    return _agent_result_validator().is_valid(result)


def agent_result_errors(result: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for err in sorted(_agent_result_validator().iter_errors(result), key=lambda e: list(e.path)):
        path = ".".join(str(p) for p in err.path) or "(root)"
        errors.append(f"{path}: {err.message}")
    return errors
