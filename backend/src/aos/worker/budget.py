"""Budget checks before model steps (worker-side; kernel enforces on posted events)."""

from __future__ import annotations

from typing import Any

from .protocol import AttemptFailed


def require_model_budget(envelope: dict[str, Any]) -> None:
    remaining = envelope.get("remaining_budget") if isinstance(envelope.get("remaining_budget"), dict) else {}
    steps = int(remaining.get("steps") or 0)
    tokens = int(remaining.get("tokens") or 0)
    if steps < 1:
        raise AttemptFailed("budget_exhausted", "No model steps remain in this attempt.")
    if tokens < 1:
        raise AttemptFailed("budget_exhausted", "No token budget remains in this attempt.")
