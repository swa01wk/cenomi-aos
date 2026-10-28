"""LangChain chat model adapter over FakeModel scripts."""

from __future__ import annotations

import html
import json
import re
import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import Field

from .fake_model import FakeModel, ScriptedTurn

_PLACEHOLDER = re.compile(r"^\{\{receipt:([A-Za-z0-9_]+)(?::(.+))?\}\}$")
_UNTRUSTED_OBS = re.compile(r'^<untrusted source="([^"]*)"(?: args="([^"]*)")? receipt="([^"]*)">')
_TRUSTED_OBS = re.compile(r"^([A-Za-z0-9_]+)\((.*?)\) -> .* \[receipt ([^\]]+)\]$", re.DOTALL)


def observed_receipts(messages: list[BaseMessage]) -> list[tuple[str, str, str]]:
    """(tool, args text, receipt ref) of each tool result rendered into the context messages."""
    out: list[tuple[str, str, str]] = []
    for message in messages:
        text = message.content if isinstance(message.content, str) else ""
        try:
            doc = json.loads(text)
        except ValueError:
            continue
        lines = doc.get("tool_observations_rendered") if isinstance(doc, dict) else None
        for line in lines or []:
            if not isinstance(line, str):
                continue
            m = _UNTRUSTED_OBS.match(line)
            if m:
                out.append((html.unescape(m.group(1)), html.unescape(m.group(2) or ""), html.unescape(m.group(3))))
                continue
            m = _TRUSTED_OBS.match(line)
            if m:
                out.append((m.group(1), m.group(2), m.group(3)))
    return out


def resolve_receipts(value: Any, receipts: list[tuple[str, str, str]]) -> Any:
    """Scripts can't know receipt refs ahead of time: `{{receipt:TOOL}}` or `{{receipt:TOOL:TEXT}}` becomes the ref
    of the latest TOOL result (whose arguments contain TEXT). Unknown placeholders stay as written."""
    if isinstance(value, dict):
        return {k: resolve_receipts(v, receipts) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_receipts(v, receipts) for v in value]
    if isinstance(value, str):
        m = _PLACEHOLDER.match(value)
        if m:
            tool, text = m.group(1), m.group(2)
            for name, args, ref in reversed(receipts):
                if name == tool and (text is None or text in args):
                    return ref
    return value


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

    def _tool_call_chunks(self, turn: ScriptedTurn, messages: list[BaseMessage]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        receipts = observed_receipts(messages)
        for i, tc in enumerate(turn.tool_calls):
            name = str(tc.get("name") or "")
            args = tc.get("args") if isinstance(tc.get("args"), dict) else {}
            args = resolve_receipts(args, receipts)
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

    def _stream_turn(self, turn: ScriptedTurn, messages: list[BaseMessage]) -> Iterator[AIMessageChunk]:
        if turn.tool_calls:
            for chunk in self._tool_call_chunks(turn, messages):
                yield AIMessageChunk(content="", tool_call_chunks=[chunk])
            um = _usage_metadata(turn)
            if um:
                yield AIMessageChunk(content="", usage_metadata=um)
            return
        parts = list(turn.stream_chunks)
        if not parts:
            parts = [turn.text]
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
        for chunk in self._stream_turn(turn, messages):
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
        for chunk in self._stream_turn(turn, messages):
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
