"""A scripted model for tests and ``aos simulate``: the POC runs end to end with no network and no LLM."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ScriptedTurn:
    text: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


class FakeModel:
    """Returns pre-scripted turns in order; records every prompt it was given."""

    def __init__(self, turns: list[ScriptedTurn]):
        self._turns = deque(turns)
        self.prompts: list[Any] = []

    def invoke(self, messages: Any) -> ScriptedTurn:
        self.prompts.append(messages)
        if not self._turns:
            raise RuntimeError("the fake model ran out of scripted turns")
        return self._turns.popleft()

    @property
    def remaining(self) -> int:
        return len(self._turns)
