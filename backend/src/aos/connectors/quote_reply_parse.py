"""Best-effort extraction of quote fields from supplier reply text (demo / IMAP ingest)."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

_HINT_HEADER = "--- Quote fields (auto-detected from email; use in save_draft) ---"


def _money_amount(raw: str) -> float | None:
    s = raw.strip()
    s = re.sub(r"(?i)^sar\s*", "", s).strip()
    s = s.replace(",", "")
    if not s:
        return None
    try:
        return float(Decimal(s))
    except (InvalidOperation, ValueError):
        return None


def _first_match(patterns: list[str], text: str, *, group: int = 1) -> str | None:
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE | re.MULTILINE)
        if m:
            g = m.group(group).strip()
            if g:
                return g
    return None


def parse_quote_reply_text(text: str) -> dict[str, Any]:
    """Return numeric quote fields when the reply contains recognizable pricing lines."""
    if not text or not text.strip():
        return {}
    body = text.replace("\r\n", "\n")

    unit_raw = _first_match(
        [
            r"(?im)^\s*unit\s*price\s*[:\-]\s*(.+)$",
            r"(?im)^\s*unit\s*[:\-]\s*(.+)$",
            r"(?i)unit\s*price\s*(?:is|:)\s*(SAR\s*[\d,]+(?:\.\d+)?)",
            r"(?i)(SAR\s*[\d,]+(?:\.\d+)?)\s*(?:per\s+unit|/unit|each)\b",
        ],
        body,
    )
    total_raw = _first_match(
        [
            r"(?im)^\s*total\s*(?:price|amount)?(?:\s*\([^)]+\))?\s*[:\-]\s*(.+)$",
            r"(?im)^\s*grand\s*total\s*[:\-]\s*(.+)$",
            r"(?i)total\s*(?:price|amount)?(?:\s*\([^)]+\))?\s*(?:is|:)\s*(SAR\s*[\d,]+(?:\.\d+)?)",
            r"(?i)total\s*(?:of|:)\s*(SAR\s*[\d,]+(?:\.\d+)?)",
        ],
        body,
    )
    if not total_raw:
        m = re.search(r"(?i)total\s*(?:\([^)]*\))?\s*[:\-]?\s*(SAR\s*[\d,]+(?:\.\d+)?)", body)
        if m:
            total_raw = m.group(1)

    lead_raw = _first_match(
        [
            r"(?im)^\s*lead\s*time\s*[:\-]\s*(.+)$",
            r"(?i)lead\s*time\s*(?:is|:)\s*(\d+)\s*(?:calendar\s*)?days?",
            r"(?i)(?:delivery|deliver(?:y|ed)?)\s*(?:in|within|lead)\s*(\d+)\s*(?:calendar\s*)?days?",
            r"(?i)(\d+)\s*(?:calendar\s*)?days?\s*lead\s*time",
        ],
        body,
    )
    warranty_raw = _first_match(
        [
            r"(?i)(\d+)\s*[\-\s]*month(?:s)?\s*warranty",
            r"(?i)warranty\s*[:\-]?\s*(\d+)\s*months?",
        ],
        body,
    )

    out: dict[str, Any] = {}
    if unit_raw:
        unit = _money_amount(unit_raw)
        if unit is not None and unit > 0:
            out["unit_price"] = unit
    if total_raw:
        total = _money_amount(total_raw)
        if total is not None and total > 0:
            out["total"] = total
    if lead_raw:
        m = re.search(r"(\d+)", lead_raw)
        if m:
            out["lead_time_days"] = int(m.group(1))
    if warranty_raw:
        out["warranty_months"] = int(warranty_raw)

    if "unit_price" not in out and "total" not in out:
        loose = re.findall(r"(?i)SAR\s*([\d,]+(?:\.\d+)?)", body)
        amounts = [a for a in (_money_amount(x) for x in loose) if a is not None and a > 0]
        if len(amounts) == 1:
            out["unit_price"] = amounts[0]
            out["total"] = amounts[0]
        elif len(amounts) >= 2:
            out["unit_price"] = amounts[0]
            out["total"] = amounts[-1]

    return out


def append_parse_hints(body: str, parsed: dict[str, Any]) -> str:
    """Append a stable, machine-readable block agents can copy into quote drafts."""
    if not parsed:
        return body
    lines = [_HINT_HEADER]
    for key in ("unit_price", "total", "lead_time_days", "warranty_months"):
        if key in parsed:
            lines.append(f"{key}: {parsed[key]}")
    block = "\n".join(lines)
    if _HINT_HEADER in body:
        return body
    return body.rstrip() + "\n\n" + block + "\n"
