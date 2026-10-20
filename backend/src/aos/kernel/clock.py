"""Kernel time (wall clock; demo offset in M2-BE-05)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import re

_DURATION_RE = re.compile(r"^(\d+)(s|m|h|d)$")
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def now() -> datetime:
    return datetime.now(UTC)


def parse_duration(text: str) -> timedelta:
    m = _DURATION_RE.match(text)
    if not m:
        raise ValueError(f"not a duration like 5d or 15m: {text!r}")
    n, unit = int(m.group(1)), m.group(2)
    return timedelta(seconds=n * _UNIT_SECONDS[unit])
