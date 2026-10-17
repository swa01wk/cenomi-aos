"""Model aliases referenced by Seats and Task contracts (docs/specs/agent/harness.md).

The worker resolves aliases to provider and model ids at runtime; the kernel only checks that a
Seat's configured alias is known.
"""

from __future__ import annotations

REGISTERED_MODEL_ALIASES: frozenset[str] = frozenset({"enterprise_reasoning"})


def model_alias_registered(alias: str) -> bool:
    return alias in REGISTERED_MODEL_ALIASES
