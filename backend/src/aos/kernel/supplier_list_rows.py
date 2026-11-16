"""Detect real vs placeholder supplier_list rows (ERP search miss, agent filler)."""

from __future__ import annotations

from typing import Any

_PLACEHOLDER_SUPPLIER_IDS = frozenset({"N/A", "NA", "NONE", "?", ""})


def supplier_list_rows(content: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(content, dict):
        return []
    rows = content.get("rows")
    if not isinstance(rows, list):
        return []
    return [r for r in rows if isinstance(r, dict)]


def supplier_row_is_real(row: dict[str, Any]) -> bool:
    sid = str(row.get("supplier_id") or "").strip().upper()
    if sid in _PLACEHOLDER_SUPPLIER_IDS:
        return False
    name = str(row.get("supplier") or "").lower()
    if "no approved suppliers" in name or "not found" in name:
        return False
    return bool(sid)


def supplier_list_has_real_rows(content: dict[str, Any] | None) -> bool:
    return any(supplier_row_is_real(r) for r in supplier_list_rows(content))
