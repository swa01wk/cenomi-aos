"""Scripted turns for FakeModel (tests and AOS_RUNTIME=fake)."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ScriptedTurn:
    text: str = ""
    stream_chunks: list[str] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    reply_blocks: list[dict[str, Any]] = field(default_factory=list)


class FakeModel:
    """Returns pre-scripted turns in order; records every prompt it was given."""

    def __init__(self, turns: list[ScriptedTurn], *, repeat_final: bool = False):
        self._turns = deque(turns)
        self._repeat_final = repeat_final
        self._last: ScriptedTurn | None = turns[-1] if turns else None
        self.prompts: list[Any] = []

    def next_turn(self) -> ScriptedTurn:
        if self._turns:
            turn = self._turns.popleft()
            self._last = turn
            return turn
        if self._repeat_final and self._last is not None:
            return self._last
        raise RuntimeError("the fake model ran out of scripted turns")

    @property
    def remaining(self) -> int:
        return len(self._turns)
