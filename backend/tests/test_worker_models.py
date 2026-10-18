"""Model alias registry (M1-AG-02)."""

from __future__ import annotations

import asyncio
import os
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from langchain_core.messages import AIMessage, HumanMessage

from aos.worker.models import (
    ModelRegistryConfig,
    build_chat_model,
    compute_cost_usd,
    load_model_registry_config,
    resolve_alias,
    validate_real_model_startup,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SMOKE_CONTRACT = {"model": {"alias": "enterprise_reasoning", "max_output_tokens": 256}}
_ECHO_COMMAND = {
    "name": "echo",
    "description": "Return the same text back to the caller.",
    "input_schema": {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    },
}


def _apply_repo_dotenv() -> None:
    """Load repo .env into os.environ for keys not already set (never log values)."""
    path = _REPO_ROOT / ".env"
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()
        if key and key not in os.environ:
            os.environ[key] = val


def _stream_chunk(raw: Any) -> Any:
    if hasattr(raw, "message") and not hasattr(raw, "tool_call_chunks"):
        return raw.message
    return raw


def _chunk_text(chunk: Any) -> str:
    content = chunk.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and part.get("type") == "text":
                text = part.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return ""


def _usage_tokens(msg: AIMessage) -> tuple[int, int]:
    meta = getattr(msg, "usage_metadata", None) or {}
    if isinstance(meta, dict):
        tin = int(meta.get("input_tokens") or 0)
        tout = int(meta.get("output_tokens") or 0)
        if tin or tout:
            return tin, tout
    resp = getattr(msg, "response_metadata", None) or {}
    usage = resp.get("token_usage") or resp.get("usage") or {}
    if isinstance(usage, dict):
        tin = int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
        tout = int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)
        return tin, tout
    return 0, 0


async def _aggregate_astream(bound, messages: list) -> tuple[AIMessage, int]:
    accumulated = None
    text_chunks = 0
    async for raw in bound.astream(messages):
        chunk = _stream_chunk(raw)
        tool_chunks = getattr(chunk, "tool_call_chunks", None) or []
        if not tool_chunks and _chunk_text(chunk):
            text_chunks += 1
        accumulated = chunk if accumulated is None else accumulated + chunk
    if accumulated is None:
        return AIMessage(content=""), text_chunks
    if isinstance(accumulated, AIMessage):
        return accumulated, text_chunks
    return (
        AIMessage(content=accumulated.content, tool_calls=getattr(accumulated, "tool_calls", None) or []),
        text_chunks,
    )


def _smoke_model():
    _apply_repo_dotenv()
    cfg = load_model_registry_config()
    resolved = validate_real_model_startup(cfg)
    llm = build_chat_model(resolved, _SMOKE_CONTRACT, cfg)
    bound = llm.bind_tools([_ECHO_COMMAND])
    return resolved, cfg, bound


class ModelRegistryTests(unittest.TestCase):
    def test_resolve_openai_default(self) -> None:
        cfg = ModelRegistryConfig(
            provider="openai",
            openai_api_key="k",
            openai_model="gpt-test",
            anthropic_api_key="",
            anthropic_model="",
            enterprise_reasoning_override="",
            temperature="",
            price_in_per_mtok="1",
            price_out_per_mtok="2",
        )
        r = resolve_alias("enterprise_reasoning", cfg)
        self.assertEqual(r.provider, "openai")
        self.assertEqual(r.model_id, "gpt-test")

    def test_resolve_anthropic(self) -> None:
        cfg = ModelRegistryConfig(
            provider="anthropic",
            openai_api_key="",
            openai_model="",
            anthropic_api_key="ak",
            anthropic_model="claude-test",
            enterprise_reasoning_override="",
            temperature="",
            price_in_per_mtok="1",
            price_out_per_mtok="1",
        )
        r = resolve_alias("enterprise_reasoning", cfg)
        self.assertEqual(r.provider, "anthropic")
        self.assertEqual(r.model_id, "claude-test")

    def test_override_wins(self) -> None:
        cfg = ModelRegistryConfig(
            provider="openai",
            openai_api_key="k",
            openai_model="gpt-test",
            anthropic_api_key="",
            anthropic_model="",
            enterprise_reasoning_override="anthropic:claude-override",
            temperature="",
            price_in_per_mtok="1",
            price_out_per_mtok="1",
        )
        r = resolve_alias("enterprise_reasoning", cfg)
        self.assertEqual(r.provider, "anthropic")
        self.assertEqual(r.model_id, "claude-override")

    def test_temperature_omitted_when_unset(self) -> None:
        cfg = ModelRegistryConfig(
            provider="openai",
            openai_api_key="k",
            openai_model="gpt-test",
            anthropic_api_key="",
            anthropic_model="",
            enterprise_reasoning_override="",
            temperature="",
            price_in_per_mtok="1",
            price_out_per_mtok="1",
        )
        resolved = resolve_alias("enterprise_reasoning", cfg)
        with mock.patch("langchain_openai.ChatOpenAI") as ctor:
            build_chat_model(resolved, {"model": {"max_output_tokens": 100}}, cfg)
            kwargs = ctor.call_args.kwargs
            self.assertNotIn("temperature", kwargs)

    def test_cost_from_prices(self) -> None:
        cfg = ModelRegistryConfig(
            provider="openai",
            openai_api_key="k",
            openai_model="m",
            anthropic_api_key="",
            anthropic_model="",
            enterprise_reasoning_override="",
            temperature="",
            price_in_per_mtok="1",
            price_out_per_mtok="2",
        )
        self.assertAlmostEqual(compute_cost_usd(1_000_000, 500_000, cfg), 2.0)

    def test_missing_key_startup_error(self) -> None:
        cfg = ModelRegistryConfig(
            provider="openai",
            openai_api_key="",
            openai_model="gpt-test",
            anthropic_api_key="",
            anthropic_model="",
            enterprise_reasoning_override="",
            temperature="",
            price_in_per_mtok="1",
            price_out_per_mtok="1",
        )
        with self.assertRaisesRegex(RuntimeError, "OPENAI_API_KEY"):
            validate_real_model_startup(cfg)

    def test_missing_prices_startup_error(self) -> None:
        cfg = ModelRegistryConfig(
            provider="openai",
            openai_api_key="k",
            openai_model="gpt-test",
            anthropic_api_key="",
            anthropic_model="",
            enterprise_reasoning_override="",
            temperature="",
            price_in_per_mtok="",
            price_out_per_mtok="",
        )
        with self.assertRaisesRegex(RuntimeError, "AOS_MODEL_PRICE"):
            validate_real_model_startup(cfg)

    @mock.patch.dict(os.environ, {"AOS_MODEL_PROVIDER": "openai", "OPENAI_MODEL": "gpt-x"}, clear=False)
    def test_load_from_env(self) -> None:
        cfg = load_model_registry_config()
        self.assertEqual(cfg.provider, "openai")
        self.assertEqual(cfg.openai_model, "gpt-x")

    def test_bind_tools_openai_function_schemas(self) -> None:
        from langchain_openai import ChatOpenAI

        commands = [
            {
                "name": "lookup_item",
                "description": "Find an item by code",
                "input_schema": {
                    "type": "object",
                    "properties": {"code": {"type": "string"}},
                    "required": ["code"],
                },
            }
        ]
        llm = ChatOpenAI(api_key="test", model="m", max_tokens=64)
        bound = llm.bind_tools(commands)
        tools = bound.kwargs.get("tools") or []
        self.assertEqual(len(tools), 1)
        fn = tools[0].get("function") if isinstance(tools[0], dict) else getattr(tools[0], "function", None)
        if fn is None and isinstance(tools[0], dict):
            fn = tools[0]
        name = fn.get("name") if isinstance(fn, dict) else getattr(fn, "name", None)
        params = fn.get("parameters") if isinstance(fn, dict) else getattr(fn, "parameters", None)
        self.assertEqual(name, "lookup_item")
        self.assertIsInstance(params, dict)
        self.assertIn("code", params.get("properties", {}))


@unittest.skipUnless(os.environ.get("AOS_REAL_MODEL") == "1", "manual real-model smoke")
class RealModelSmokeTests(unittest.TestCase):
    """One live-API run, in ONE event loop.

    langchain-openai shares a cached async HTTP client across every ChatOpenAI in the process. Separate
    IsolatedAsyncioTestCase methods each get a new loop, so the second test reuses a pooled connection
    from the first test's closed loop ("Event loop is closed"). The worker itself runs a single loop, so
    this only affects tests; both checks therefore run inside one asyncio.run().
    """

    def test_live_streaming_and_tool_call(self) -> None:
        asyncio.run(self._live_checks())

    async def _live_checks(self) -> None:
        resolved, cfg, bound = _smoke_model()

        with self.subTest("text reply streams with usage"):
            messages = [HumanMessage(content="Reply in exactly one short sentence: what is 2+2?")]
            msg, text_chunks = await asyncio.wait_for(_aggregate_astream(bound, messages), timeout=120.0)
            self.assertGreaterEqual(text_chunks, 2, "expected multiple streamed text chunks")
            tin, tout = _usage_tokens(msg)
            self.assertGreater(tin, 0)
            self.assertGreater(tout, 0)
            cost = compute_cost_usd(tin, tout, cfg)
            print(
                f"real-model smoke (text): provider={resolved.provider} model={resolved.model_id} "
                f"tokens_in={tin} tokens_out={tout} cost_usd={cost:.6f}"
            )

        with self.subTest("tool call through bind_tools"):
            messages = [
                HumanMessage(
                    content=(
                        "You must call the echo tool once with text exactly "
                        '"smoke-echo-42". Do not answer without using the tool.'
                    )
                )
            ]
            msg, _text_chunks = await asyncio.wait_for(_aggregate_astream(bound, messages), timeout=120.0)
            tool_calls = list(getattr(msg, "tool_calls", None) or [])
            self.assertGreaterEqual(len(tool_calls), 1, msg)
            echo = next((tc for tc in tool_calls if tc.get("name") == "echo"), None)
            self.assertIsNotNone(echo, tool_calls)
            args = echo.get("args") if isinstance(echo.get("args"), dict) else {}
            self.assertEqual(str(args.get("text") or ""), "smoke-echo-42")
            tin, tout = _usage_tokens(msg)
            cost = compute_cost_usd(tin, tout, cfg)
            print(
                f"real-model smoke (tool): provider={resolved.provider} model={resolved.model_id} "
                f"tokens_in={tin} tokens_out={tout} cost_usd={cost:.6f}"
            )


if __name__ == "__main__":
    unittest.main()
