"""Kernel time (wall clock; demo offset when AOS_DEMO=1)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import re

_DURATION_RE = re.compile(r"^(\d+)(s|m|h|d)$")
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}

_demo_enabled = False
_offset_seconds = 0
_frozen_wall: datetime | None = None


def configure(*, demo_enabled: bool, offset_seconds: int = 0) -> None:
    global _demo_enabled, _offset_seconds
    _demo_enabled = demo_enabled
    _offset_seconds = offset_seconds


def set_offset(seconds: int) -> None:
    global _offset_seconds
    _offset_seconds = int(seconds)


def offset_seconds() -> int:
    return _offset_seconds


def demo_enabled() -> bool:
    return _demo_enabled


def set_frozen_wall(at: datetime | None) -> None:
    global _frozen_wall
    _frozen_wall = at


def wall_now() -> datetime:
    if _frozen_wall is not None:
        return _frozen_wall
    return datetime.now(UTC)


def now() -> datetime:
    if _demo_enabled:
        return wall_now() + timedelta(seconds=_offset_seconds)
    return wall_now()


def parse_duration(text: str) -> timedelta:
    m = _DURATION_RE.match(text)
    if not m:
        raise ValueError(f"not a duration like 5d or 15m: {text!r}")
    n, unit = int(m.group(1)), m.group(2)
    return timedelta(seconds=n * _UNIT_SECONDS[unit])


def iso_z(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")
