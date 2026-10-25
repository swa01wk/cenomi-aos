"""Shared artifact walking for verifiers."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterator


def iter_field_values(
    content: dict[str, Any],
    *,
    row_based: bool,
    field_names: set[str] | None = None,
) -> Iterator[tuple[str, Any]]:
    if row_based:
        rows = content.get("rows")
        if not isinstance(rows, list):
            return
        for row in rows:
            if not isinstance(row, dict):
                continue
            for name, val in row.items():
                if field_names is not None and name not in field_names:
                    continue
                yield name, val
        return
    if not isinstance(content, dict):
        return
    for name, val in content.items():
        if field_names is not None and name not in field_names:
            continue
        yield name, val


def field_classification(
    artifact_type: str,
    field_name: str,
    artifact_types: dict[str, dict[str, Any]],
) -> str:
    spec = artifact_types.get(artifact_type) or {}
    fields = spec.get("fields") or {}
    fdoc = fields.get(field_name) if isinstance(fields, dict) else None
    if isinstance(fdoc, dict) and fdoc.get("classification"):
        return str(fdoc["classification"])
    if spec.get("classification"):
        return str(spec["classification"])
    return "internal"


def parse_date_value(val: Any) -> date | None:
    if val is None:
        return None
    if isinstance(val, date) and not isinstance(val, datetime):
        return val
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, str):
        text = val.strip()
        if len(text) >= 10:
            try:
                return date.fromisoformat(text[:10])
            except ValueError:
                return None
    return None


def is_typed_string(val: Any) -> bool:
    return isinstance(val, str) and bool(val.strip())


def is_typed_integer(val: Any) -> bool:
    return isinstance(val, int) and not isinstance(val, bool)


def is_typed_number(val: Any) -> bool:
    return isinstance(val, (int, float, Decimal)) and not isinstance(val, bool)


def money_number(val: Any) -> int | float | None:
    if isinstance(val, bool):
        return None
    if isinstance(val, int):
        return val
    if isinstance(val, float):
        return val
    if isinstance(val, Decimal):
        return float(val)
    if isinstance(val, str):
        stripped = val.strip().replace(",", "")
        if stripped.isdigit():
            return int(stripped)
        try:
            return float(stripped)
        except ValueError:
            return None
    return None
