"""brief_schema: the brief is complete, its delivery date is far enough out and its category came from the ERP."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from psycopg import AsyncConnection

from ..kernel import clock
from . import _records

ARTIFACT_TYPE = "brief"
CATEGORY_TOOL = "browse_categories"
MIN_LEAD_DAYS = 3
_TEXT_FIELDS = ("title", "category", "specification", "delivery_site")


def _blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def check_brief(content: dict[str, Any], *, today: date, category_ids: set[str]) -> list[str]:
    """One finding per field that breaks a rule; empty when the brief passes."""
    findings: list[str] = []
    for name in _TEXT_FIELDS:
        if _blank(content.get(name)):
            findings.append(f"{name} is missing.")

    quantity = content.get("quantity")
    if quantity is None:
        findings.append("quantity is missing.")
    elif isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
        findings.append("quantity must be a whole number above 0.")

    earliest = today + timedelta(days=MIN_LEAD_DAYS)
    raw_date = content.get("delivery_date")
    if _blank(raw_date):
        findings.append("delivery_date is missing.")
    else:
        try:
            delivery = date.fromisoformat(str(raw_date))
        except ValueError:
            findings.append("delivery_date must be a date like 2026-11-20.")
        else:
            if delivery < earliest:
                findings.append(
                    f"delivery_date must be {earliest.isoformat()} or later ({MIN_LEAD_DAYS} days from today)."
                )

    category = content.get("category")
    if not _blank(category) and str(category) not in category_ids:
        findings.append(f"category must be an id that {CATEGORY_TOOL} returned in this Task.")
    return findings


def category_ids(observations: list[dict[str, Any]]) -> set[str]:
    return {
        str(item["id"])
        for obs in observations
        if obs.get("tool") == CATEGORY_TOOL
        for item in _records.items(obs)
        if item.get("id")
    }


async def verify(conn: AsyncConnection, gate: Any, result: dict[str, Any], defs: dict) -> tuple[str, list[str]]:
    briefs = [o for o in await _records.outputs(conn, result) if o.artifact_type == ARTIFACT_TYPE]
    if not briefs:
        return "REWORK", ["The brief was not saved with this result."]
    ids = category_ids(await _records.observations(conn, gate.task_id))
    findings = check_brief(briefs[-1].content, today=clock.now().date(), category_ids=ids)
    return ("REWORK", findings) if findings else ("PASS", [])
