"""Checkpointed assist graph state (contract and envelope are re-fetched each run)."""

from __future__ import annotations

from typing import Any, TypedDict


class AssistGraphState(TypedDict, total=False):
    ids: dict[str, str]
    worker_notes: list[str]
    draft_422_counts: dict[str, int]
    stream_seq: int
    assemble_reason: str
    pending_tool_calls: list[dict[str, Any]]
    model_reply_text: str
    reply_blocks: list[dict[str, Any]]
    agent_result: dict[str, Any]
