"""Verifier brief_schema: required brief fields and ERP category (request_intake spec)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Literal

from ._fields import is_typed_integer, is_typed_string, money_number, parse_date_value

Verdict = Literal["PASS", "REWORK", "FAIL"]


def _category_ids_from_receipts(tool_receipts: list[dict[str, Any]]) -> set[str]:
    ids: set[str] = set()
    for rec in tool_receipts:
        if rec.get("tool") != "browse_categories":
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


def _parse_now(inp: dict[str, Any]) -> datetime:
    raw = inp.get("now")
    if isinstance(raw, datetime):
        return raw
    if isinstance(raw, str):
        text = raw.strip().replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            pass
    return datetime.now()


def verify(inp: dict[str, Any]) -> tuple[Verdict, list[str]]:
    outputs = inp.get("outputs") or []
    brief = None
    for out in outputs:
        if out.get("artifact_type") == "brief":
            brief = out.get("content")
            break
    if not isinstance(brief, dict):
        return "REWORK", ["brief: missing output"]

    findings: list[str] = []
    today = _parse_now(inp).date()
    min_delivery = today + timedelta(days=3)
    erp_categories = _category_ids_from_receipts(inp.get("tool_receipts") or [])

    if not is_typed_string(brief.get("title")):
        findings.append("title: required string missing or empty")
    if not is_typed_string(brief.get("category")):
        findings.append("category: required string missing or empty")
    elif str(brief.get("category")) not in erp_categories:
        findings.append("category: not returned by browse_categories for this task")

    qty = brief.get("quantity")
    if not is_typed_integer(qty) or int(qty) <= 0:
        findings.append("quantity: must be an integer greater than zero")

    if not is_typed_string(brief.get("specification")):
        findings.append("specification: required string missing or empty")

    delivery = parse_date_value(brief.get("delivery_date"))
    if delivery is None:
        findings.append("delivery_date: required date missing or invalid")
    elif delivery < min_delivery:
        findings.append("delivery_date: must be at least three days from today")

    if not is_typed_string(brief.get("delivery_site")):
        findings.append("delivery_site: required string missing or empty")

    # Typed check for money field when present (not required on brief).
    if "budget_guidance" in brief and brief["budget_guidance"] is not None:
        if money_number(brief["budget_guidance"]) is None:
            findings.append("budget_guidance: must be a number when set")

    if findings:
        return "REWORK", findings
    return "PASS", []
