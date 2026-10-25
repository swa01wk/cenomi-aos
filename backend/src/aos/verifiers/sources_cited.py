"""Verifier sources_cited: supplier_list rows cite this task's ERP receipts (supplier_lookup spec)."""

from __future__ import annotations

from typing import Any, Literal

Verdict = Literal["PASS", "REWORK", "FAIL"]


def _source_ref(entry: Any) -> str | None:
    if isinstance(entry, str) and entry.strip():
        return entry.strip()
    if isinstance(entry, dict):
        for key in ("receipt_ref", "receipt_id", "ref"):
            val = entry.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    return None


def _task_receipt_refs(tool_receipts: list[dict[str, Any]]) -> set[str]:
    return {str(r["receipt_ref"]) for r in tool_receipts if r.get("receipt_ref")}


def _search_supplier_ids(tool_receipts: list[dict[str, Any]]) -> set[str]:
    ids: set[str] = set()
    for rec in tool_receipts:
        if rec.get("tool") != "search_suppliers":
            continue
        content = rec.get("content")
        if not isinstance(content, dict):
            continue
        items = content.get("items")
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, dict) and item.get("id"):
                ids.add(str(item["id"]))
    return ids


def verify(inp: dict[str, Any]) -> tuple[Verdict, list[str]]:
    outputs = inp.get("outputs") or []
    content = None
    for out in outputs:
        if out.get("artifact_type") == "supplier_list":
            content = out.get("content")
            break
    if not isinstance(content, dict):
        return "REWORK", ["supplier_list: missing output"]

    rows = content.get("rows")
    if not isinstance(rows, list):
        return "REWORK", ["supplier_list: rows must be an array"]

    artifact_types = inp.get("artifact_types") or {}
    sl_spec = artifact_types.get("supplier_list") or {}
    row_key = str(sl_spec.get("row_key") or "supplier_id")

    tool_receipts = inp.get("tool_receipts") or []
    allowed_refs = _task_receipt_refs(tool_receipts)
    search_ids = _search_supplier_ids(tool_receipts)

    findings: list[str] = []
    scored: list[tuple[int, float, str]] = []

    for row in rows:
        if not isinstance(row, dict):
            continue
        key_val = row.get(row_key)
        row_label = str(key_val) if key_val is not None else "?"
        sources = row.get("sources")
        if not isinstance(sources, list) or not sources:
            findings.append(f"{row_key} {row_label}: no sources cited")
            continue
        refs = [_source_ref(s) for s in sources]
        refs = [r for r in refs if r]
        if not refs:
            findings.append(f"{row_key} {row_label}: no sources cited")
            continue
        for ref in refs:
            if ref not in allowed_refs:
                findings.append(f"{row_key} {row_label}: source not from this task")
        sid = row.get("supplier_id")
        if sid is not None and str(sid) not in search_ids:
            findings.append(f"{row_key} {row_label}: supplier not in search_suppliers results")

        rank = row.get("rank")
        score = row.get("score")
        if isinstance(rank, int) and isinstance(score, (int, float)):
            scored.append((rank, float(score), row_label))

    n = len(rows)
    if n and not findings:
        ranks = sorted(r for r, _, _ in scored)
        expected = list(range(1, n + 1))
        if ranks != expected:
            findings.append("rank: must be 1 through n with no gaps")
        by_rank = sorted(scored, key=lambda t: t[0])
        for i in range(len(by_rank) - 1):
            if by_rank[i][1] < by_rank[i + 1][1]:
                findings.append("rank: must follow score descending")
                break

    if findings:
        return "REWORK", findings
    return "PASS", []
