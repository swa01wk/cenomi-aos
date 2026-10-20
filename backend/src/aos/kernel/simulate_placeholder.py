"""Deterministic artifact placeholders for workflow simulation (M2-BE-06)."""

from __future__ import annotations

from typing import Any

from aos.registry.kinds import ArtifactType, FieldSpec


def _field_value(name: str, field: FieldSpec, *, row_index: int | None = None) -> Any:
    suffix = f"-{row_index}" if row_index is not None else ""
    if field.type == "integer":
        return (row_index or 0) + 1
    if field.type in ("number", "money"):
        return float((row_index or 0) + 1)
    if field.type == "date":
        return "2026-12-01"
    if field.type == "datetime":
        return "2026-12-01T12:00:00Z"
    if field.type == "list":
        if name == "sources":
            return [{"ref": f"sim-source{suffix}"}]
        if name == "lines":
            return [{"description": "sim line", "quantity": 1, "unit_price": 1.0}]
        if name == "attachments":
            return []
        return []
    if field.type == "boolean":
        return True
    if field.type == "object":
        return {}
    if name == "category":
        return "CAT-SIM"
    return f"sim-{name}{suffix}"


def placeholder_content(artifact_type: ArtifactType) -> dict[str, Any]:
    spec = artifact_type.spec
    if spec.row_based:
        row_key = spec.row_key or "id"
        rows: list[dict[str, Any]] = []
        for i in range(3):
            row: dict[str, Any] = {}
            for fname, fspec in spec.fields.items():
                if fname == row_key:
                    row[fname] = f"sim-{i + 1}"
                elif fname == "rank":
                    row[fname] = i + 1
                else:
                    row[fname] = _field_value(fname, fspec, row_index=i)
            rows.append(row)
        return {"rows": rows}
    content: dict[str, Any] = {}
    for fname, fspec in spec.fields.items():
        content[fname] = _field_value(fname, fspec)
    return content
