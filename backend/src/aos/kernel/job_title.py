"""Human-readable job titles from chat or brief content."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from .intake_routing import _hint_score

if TYPE_CHECKING:
    from psycopg import AsyncConnection

_SEGMENT = re.compile(r"\s*[·\n]+\s*")
_SMALL = frozenset(
    {
        "hi",
        "hey",
        "hello",
        "yo",
        "sup",
        "ok",
        "okay",
        "yes",
        "no",
        "nah",
        "naah",
        "thanks",
        "thank you",
        "nope",
        "sure",
    }
)


def _truncate(text: str, limit: int = 100) -> str:
    t = " ".join(text.split())
    if len(t) <= limit:
        return t
    return t[: limit - 1].rstrip() + "…"


def _segment_score(segment: str, hints: list[str]) -> int:
    lower = segment.lower().strip()
    if not lower or lower in _SMALL:
        return -1
    words = lower.split()
    if len(words) <= 2 and lower in _SMALL:
        return -1
    if all(w in _SMALL for w in words):
        return -1
    score = _hint_score(segment, hints)
    if any(ch.isdigit() for ch in segment):
        score += 1
    if len(words) >= 4:
        score += 1
    return score


def derive_job_title(message: str, *, hints: list[str] | None = None) -> str:
    """Pick the most meaningful line from a starter message or handoff blob."""
    raw = (message or "").strip()
    if not raw:
        return "New request"
    hint_list = hints or []
    parts = [p.strip() for p in _SEGMENT.split(raw) if p.strip()]
    if not parts:
        parts = [raw]
    scored = [( _segment_score(p, hint_list), len(p), p) for p in parts]
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    for score, _, text in scored:
        if score >= 1:
            return _truncate(text)
    for _, _, text in scored:
        if _segment_score(text, hint_list) >= 0 and len(text.split()) >= 3:
            return _truncate(text)
    return _truncate(parts[0] if parts else raw)


async def display_instance_title(conn: AsyncConnection, instance_id: str, stored: str) -> str:
    """Brief name when available, else a cleaned title from the stored starter text."""
    cur = await conn.execute(
        "select name from work.artifacts where instance_id = %s and artifact_type = 'brief'"
        " and latest_version >= 1 order by latest_version desc limit 1",
        (instance_id,),
    )
    row = await cur.fetchone()
    if row is not None:
        name = str(row[0] or "").strip()
        if name and name.lower() not in ("brief", "request brief"):
            return name
    cleaned = derive_job_title(stored)
    return cleaned or stored
