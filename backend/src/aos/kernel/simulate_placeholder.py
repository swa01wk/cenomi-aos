"""Deterministic artifact placeholders for workflow simulation (M2-BE-06).

Generated only from each field's declared type, never from field names: platform code doesn't know a pack's
fields. Rows of row-based types get distinct row_key values.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from aos.registry.kinds import ArtifactType, FieldSpec

from . import clock


def _field_value(name: str, field: FieldSpec, *, row_index: int | None = None) -> Any:
    n = (row_index or 0) + 1
    if field.type == "integer":
        return n
    if field.type in ("number", "money"):
        return float(n)
    if field.type == "date":
        return (clock.now() + timedelta(days=30)).date().isoformat()
    if field.type == "datetime":
        return clock.iso_z(clock.now() + timedelta(days=30))
    if field.type == "list":
        return []
    if field.type == "boolean":
        return True
    if field.type == "object":
        return {}
    suffix = f"-{row_index}" if row_index is not None else ""
    return f"sim-{name}{suffix}"


def placeholder_content(artifact_type: ArtifactType) -> dict[str, Any]:
    spec = artifact_type.spec
    if spec.row_based:
        row_key = spec.row_key
        rows: list[dict[str, Any]] = []
        for i in range(3):
            row: dict[str, Any] = {}
            for fname, fspec in spec.fields.items():
                row[fname] = f"sim-{i + 1}" if fname == row_key else _field_value(fname, fspec, row_index=i)
            rows.append(row)
        return {"rows": rows}
    return {fname: _field_value(fname, fspec) for fname, fspec in spec.fields.items()}
