"""LangChain chat model adapter over FakeModel scripts."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import Field

from .fake_model import FakeModel, ScriptedTurn


def _usage_metadata(turn: ScriptedTurn) -> dict[str, Any]:
    raw = turn.usage if isinstance(turn.usage, dict) else {}
    tin = int(raw.get("tokens_in") or 0)
    tout = int(raw.get("tokens_out") or 0)
    if not tin and not tout:
        return {}
    return {"input_tokens": tin, "output_tokens": tout, "total_tokens": tin + tout}


class FakeChatModel(BaseChatModel):
    """Drives the assist graph from YAML turns without network calls."""

    fake: FakeModel = Field(exclude=True)
    model_name: str = "fake"

    @property
    def _llm_type(self) -> str:
        return "aos-fake"

    def _tool_call_chunks(self, turn: ScriptedTurn) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for i, tc in enumerate(turn.tool_calls):
            name = str(tc.get("name") or "")
            args = tc.get("args") if isinstance(tc.get("args"), dict) else {}
            tid = str(tc.get("id") or uuid.uuid4())
            out.append(
                {
                    "name": name,
                    "args": json.dumps(args, sort_keys=True),
                    "id": tid,
                    "index": i,
                    "type": "tool_call_chunk",
                }
            )
        return out

    def _stream_turn(self, turn: ScriptedTurn) -> Iterator[AIMessageChunk]:
        if turn.tool_calls:
            for chunk in self._tool_call_chunks(turn):
                yield AIMessageChunk(content="", tool_call_chunks=[chunk])
            um = _usage_metadata(turn)
            if um:
                yield AIMessageChunk(content="", usage_metadata=um)
            return
        parts = list(turn.stream_chunks)
        if not parts:
            text = turn.reply_text or turn.text or ""
            parts = [text] if text else [""]
        for i, part in enumerate(parts):
            um = _usage_metadata(turn) if i == len(parts) - 1 else None
            if um:
                yield AIMessageChunk(content=part, usage_metadata=um)
            else:
                yield AIMessageChunk(content=part)

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        self.fake.prompts.append(messages)
        turn = self.fake.next_turn()
        merged: AIMessageChunk | None = None
        for chunk in self._stream_turn(turn):
            merged = chunk if merged is None else merged + chunk
        if merged is None:
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content=""))])
        return ChatResult(generations=[ChatGeneration(message=merged)])

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        self.fake.prompts.append(messages)
        turn = self.fake.next_turn()
        for chunk in self._stream_turn(turn):
            yield ChatGenerationChunk(message=chunk)

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        for item in self._stream(messages, stop=stop, run_manager=run_manager, **kwargs):
            yield item

    def bind_tools(self, tools: Any, **kwargs: Any) -> FakeChatModel:
        return self


def chat_model_from_script(script) -> FakeChatModel:
    from .scripts_loader import FakeScript

    if isinstance(script, FakeScript):
        fm = FakeModel(script.turns, repeat_final=script.repeat_final)
    else:
        fm = script
    return FakeChatModel(fake=fm)
