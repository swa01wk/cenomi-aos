"""Model alias registry for configuration checks (harness resolves aliases at runtime)."""

from __future__ import annotations

import os

DEFAULT_ALIASES = frozenset({"enterprise_reasoning"})


def registered_aliases() -> frozenset[str]:
    raw = os.environ.get("AOS_REGISTERED_MODEL_ALIASES", "enterprise_reasoning")
    parts = {p.strip() for p in raw.split(",") if p.strip()}
    return frozenset(parts) if parts else DEFAULT_ALIASES


def alias_registered(alias: str) -> bool:
    return alias in registered_aliases()
