"""Demo/testing: vendor reply windows from the brief (user numbers always mean minutes)."""

from __future__ import annotations

import os
import re
from typing import Any

DEFAULT_DEMO_REPLY_MINUTES = 1.5

_NUMBER_RE = re.compile(r"(\d+(?:\.\d+)?)")


def demo_short_deadline_enabled() -> bool:
    return os.environ.get("AOS_RFQ_DEMO_SHORT_DEADLINE", "1").strip().lower() in ("1", "true", "yes")


def parse_demo_reply_minutes(raw: Any) -> float:
    """First number in the user's text is treated as minutes (days/hours labels ignored in demo)."""
    if raw is None:
        return DEFAULT_DEMO_REPLY_MINUTES
    text = str(raw).strip()
    if not text:
        return DEFAULT_DEMO_REPLY_MINUTES
    m = _NUMBER_RE.search(text)
    if not m:
        return DEFAULT_DEMO_REPLY_MINUTES
    try:
        value = float(m.group(1))
    except ValueError:
        return DEFAULT_DEMO_REPLY_MINUTES
    if value <= 0:
        return DEFAULT_DEMO_REPLY_MINUTES
    return value


def demo_reply_timer_duration(minutes: float) -> str:
    """Duration string for ``clock.parse_duration`` (integer seconds)."""
    seconds = max(1, int(round(minutes * 60)))
    return f"{seconds}s"


def format_reply_deadline_line(minutes: float, *, by: str) -> str:
    label = f"{minutes:g} minute{'s' if minutes != 1 else ''}"
    return f"Reply deadline: Please send your quotation within {label} (by {by})."


async def brief_reply_duration_for_instance(conn, instance_id: str) -> str:
    """Timer duration for quote_deadline from the brief (demo: first number = minutes)."""
    cur = await conn.execute(
        "select v.content from work.artifacts a"
        " join work.artifact_versions v on v.artifact_id = a.id and v.version = a.latest_version"
        " where a.instance_id = %s and a.artifact_type = 'brief' limit 1",
        (instance_id,),
    )
    row = await cur.fetchone()
    brief: dict[str, Any] = {}
    if row is not None:
        raw = row[0]
        if isinstance(raw, dict):
            brief = raw
        elif raw is not None:
            import json

            brief = json.loads(raw or "{}")
    minutes = parse_demo_reply_minutes(brief.get("vendor_reply_deadline"))
    return demo_reply_timer_duration(minutes)
