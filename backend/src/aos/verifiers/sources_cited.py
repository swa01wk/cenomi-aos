"""sources_cited: every ranked row cites receipts from this Task's own tool calls, and the ranking is consistent."""

from __future__ import annotations

from typing import Any

from psycopg import AsyncConnection

from . import _records

ARTIFACT_TYPE = "supplier_list"
SEARCH_TOOL = "search_suppliers"


def _source_refs(row: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for source in row.get("sources") or []:
        if isinstance(source, str):
            refs.append(source)
        elif isinstance(source, dict) and source.get("receipt_ref"):
            refs.append(str(source["receipt_ref"]))
    return refs


def _row_name(row: dict[str, Any], index: int) -> str:
    label = row.get("supplier") or row.get("supplier_id")
    return f"Row {index + 1} ({label})" if label else f"Row {index + 1}"


def check_rows(rows: list[dict[str, Any]], *, receipt_refs: set[str], searched_ids: set[str]) -> list[str]:
    """One finding per broken row, then one for the ranking as a whole; empty when the list passes."""
    if not rows:
        return ["The list has no rows."]
    findings: list[str] = []
    for i, row in enumerate(rows):
        name = _row_name(row, i)
        refs = _source_refs(row)
        if not refs:
            findings.append(f"{name} cites no source.")
        elif unknown := [r for r in refs if r not in receipt_refs]:
            findings.append(f"{name} cites {len(unknown)} source(s) that are not receipts from this Task's tool calls.")
        if str(row.get("supplier_id") or "") not in searched_ids:
            findings.append(f"{name} has a supplier_id that no {SEARCH_TOOL} call in this Task returned.")

    ranks = [row.get("rank") for row in rows]
    if not all(isinstance(r, int) and not isinstance(r, bool) for r in ranks) or sorted(ranks) != list(
        range(1, len(rows) + 1)
    ):
        findings.append(f"Ranks must run 1 to {len(rows)} with no gaps or repeats.")
    else:
        by_rank = sorted(rows, key=lambda r: r["rank"])
        scores = [r.get("score") for r in by_rank]
        numeric = all(isinstance(s, (int, float)) and not isinstance(s, bool) for s in scores)
        if not numeric or any(a < b for a, b in zip(scores, scores[1:])):
            findings.append("Rank order must follow score, highest first.")
    return findings


def receipts(observations: list[dict[str, Any]]) -> tuple[set[str], set[str]]:
    """(every receipt ref of this Task, supplier ids its searches returned)."""
    refs = {str(o["receipt_ref"]) for o in observations if o.get("receipt_ref")}
    searched = {
        str(item["id"])
        for o in observations
        if o.get("tool") == SEARCH_TOOL
        for item in _records.items(o)
        if item.get("id")
    }
    return refs, searched


async def verify(conn: AsyncConnection, gate: Any, result: dict[str, Any], defs: dict) -> tuple[str, list[str]]:
    lists = [o for o in await _records.outputs(conn, result) if o.artifact_type == ARTIFACT_TYPE]
    if not lists:
        return "REWORK", ["The supplier list was not saved with this result."]
    refs, searched = receipts(await _records.observations(conn, gate.task_id))
    rows = [r for r in lists[-1].content.get("rows") or [] if isinstance(r, dict)]
    findings = check_rows(rows, receipt_refs=refs, searched_ids=searched)
    return ("REWORK", findings) if findings else ("PASS", [])
