"""Detect when a chat message is specific enough to start structured intake."""

from __future__ import annotations

from typing import Any

from .intake_routing import _hint_score, _text_field_score


def message_indicates_request_detail(message: str, workflow_doc: dict[str, Any]) -> bool:
    """True when the message looks like a concrete request, not small talk."""
    spec = workflow_doc.get("spec") or {}
    hints = spec.get("intake_hints") or []
    if not isinstance(hints, list):
        hints = []
    score = _hint_score(message, hints)
    score += _text_field_score(message, str(spec.get("title") or ""), str(spec.get("description") or ""))
    if score >= 1:
        return True
    text = message.strip()
    if not text:
        return False
    if any(ch.isdigit() for ch in text) and len(text.split()) >= 4:
        return True
    return len(text) > 120
