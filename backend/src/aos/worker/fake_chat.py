"""LangChain chat model adapter over FakeModel scripts."""

from __future__ import annotations

import uuid
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool as lc_tool  # noqa: F401 — re-export for typing
from pydantic import Field

from .fake_model import FakeModel, ScriptedTurn


class FakeChatModel(BaseChatModel):
    """Drives the assist graph from YAML turns without network calls."""

    fake: FakeModel = Field(exclude=True)
    model_name: str = "fake"

    @property
    def _llm_type(self) -> str:
        return "aos-fake"

    def _turn_to_ai(self, turn: ScriptedTurn) -> AIMessage:
        tool_calls = []
        for tc in turn.tool_calls:
            name = str(tc.get("name") or "")
            args = tc.get("args") if isinstance(tc.get("args"), dict) else {}
            tid = str(tc.get("id") or uuid.uuid4())
            tool_calls.append({"name": name, "args": args, "id": tid, "type": "tool_call"})
        content = turn.text or ""
        if tool_calls:
            return AIMessage(content=content or "", tool_calls=tool_calls)
        return AIMessage(content=content)

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        self.fake.prompts.append(messages)
        turn = self.fake.next_turn()
        msg = self._turn_to_ai(turn)
        meta = dict(turn.usage)
        gen = ChatGeneration(message=msg, generation_info=meta)
        return ChatResult(generations=[gen])

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

    def bind_tools(self, tools: Any, **kwargs: Any) -> FakeChatModel:
        return self

    @property
    def last_turn(self) -> ScriptedTurn | None:
        return self.fake._last  # noqa: SLF001 — test hook


def chat_model_from_script(script) -> FakeChatModel:
    from .scripts_loader import FakeScript

    if isinstance(script, FakeScript):
        fm = FakeModel(script.turns, repeat_final=script.repeat_final)
    else:
        fm = script
    return FakeChatModel(fake=fm)
