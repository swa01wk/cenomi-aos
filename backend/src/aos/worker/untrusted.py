"""Wrap external tool content so it cannot break out of untrusted markers in prompts."""

from __future__ import annotations

import html
import json
from typing import Any


def escape_untrusted_text(text: str) -> str:
    """Escape so model-facing XML-like wrappers cannot be closed by payload text."""
    return html.escape(text, True)


def _canonical_args(args: Any) -> str:
    return json.dumps(args if isinstance(args, dict) else {}, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def wrap_untrusted(content: Any, *, source: str, args: dict[str, Any] | None = None) -> str:
    src = escape_untrusted_text(source)
    attrs = f' source="{src}"'
    if args is not None:
        attrs += f' args="{escape_untrusted_text(_canonical_args(args))}"'
    if isinstance(content, str):
        body = escape_untrusted_text(content)
    else:
        body = escape_untrusted_text(json.dumps(content, sort_keys=True, ensure_ascii=False))
    return f"<untrusted{attrs}>{body}</untrusted>"


def format_observation_for_context(obs: dict[str, Any]) -> str:
    """One earlier tool call: the tool, the arguments it was called with, and its result."""
    tool = str(obs.get("tool") or "tool")
    content = obs.get("content")
    args = obs.get("args") if isinstance(obs.get("args"), dict) else None
    if obs.get("untrusted"):
        return wrap_untrusted(content, source=tool, args=args)
    text = content if isinstance(content, str) else json.dumps(content, sort_keys=True, ensure_ascii=False)
    return f"{tool}({_canonical_args(args)}) -> {text}" if args is not None else text


def already_observed(observations: Any, tool: str, args: Any) -> bool:
    """True when this attempt already called `tool` with the same arguments (its result is in the context)."""
    if not isinstance(observations, list):
        return False
    key = _canonical_args(args)
    return any(
        isinstance(o, dict) and o.get("tool") == tool and isinstance(o.get("args"), dict)
        and _canonical_args(o["args"]) == key
        for o in observations
    )
