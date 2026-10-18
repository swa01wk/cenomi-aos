"""Wrap external tool content so it cannot break out of untrusted markers in prompts."""

from __future__ import annotations

import html
import json
from typing import Any


def escape_untrusted_text(text: str) -> str:
    """Escape so model-facing XML-like wrappers cannot be closed by payload text."""
    return html.escape(text, True)


def wrap_untrusted(content: Any, *, source: str) -> str:
    src = escape_untrusted_text(source)
    if isinstance(content, str):
        body = escape_untrusted_text(content)
    else:
        body = escape_untrusted_text(json.dumps(content, sort_keys=True, ensure_ascii=False))
    return f'<untrusted source="{src}">{body}</untrusted>'


def format_observation_for_context(obs: dict[str, Any]) -> str:
    tool = str(obs.get("tool") or "tool")
    content = obs.get("content")
    if obs.get("untrusted"):
        return wrap_untrusted(content, source=tool)
    if isinstance(content, str):
        return content
    return json.dumps(content, sort_keys=True, ensure_ascii=False)
