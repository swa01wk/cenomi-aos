"""Checkpointed assist graph state (contract and envelope are re-fetched each run)."""

from __future__ import annotations

from typing import Any, TypedDict


class AssistGraphState(TypedDict, total=False):
    ids: dict[str, str]
    worker_notes: list[str]
    # What this attempt has done so far (drafts saved, questions held, lookups), shown to the model every step:
    # a step starts from the context envelope, not a chat history, so it can't otherwise see its own actions.
    actions_this_reply: list[str]
    draft_422_counts: dict[str, int]
    stream_seq: int
    assemble_reason: str
    pending_tool_calls: list[dict[str, Any]]
    model_reply_text: str
    reply_blocks: list[dict[str, Any]]
    agent_result: dict[str, Any]
    saved_in_attempt: dict[str, dict[str, Any]]
    ended_needs_input: bool
    pending_submit: dict[str, Any]


TaskGraphState = AssistGraphState
