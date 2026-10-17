"""Committed refusals: Decision Record + audit in the same transaction, then Problem response."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CommittedRefusal:
    code: str
    status: int
    title: str
    detail: str
    decision_id: str
    rule: str | None = None
