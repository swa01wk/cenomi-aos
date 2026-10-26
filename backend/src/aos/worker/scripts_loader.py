"""Load fake model scripts from worker/scripts/*.yaml."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .fake_model import ScriptedTurn

_PKG = Path(__file__).resolve().parent
SCRIPTS_DIR = _PKG / "scripts"


@dataclass
class FakeScript:
    turns: list[ScriptedTurn]
    repeat_final: bool = False
    attempt_turns: list[list[ScriptedTurn]] | None = None


def script_path(name: str) -> Path:
    path = Path(name)
    if path.is_file():
        return path
    candidate = SCRIPTS_DIR / name
    if candidate.is_file():
        return candidate
    if not name.endswith(".yaml"):
        candidate = SCRIPTS_DIR / f"{name}.yaml"
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"fake model script not found: {name!r}")


def task_script(contract: dict[str, Any], scenario: str = "happy") -> str | None:
    """The fake model script for a Task: ``<template>.<scenario>``, else ``<skill>.<scenario>``; a scenario a Task
    has no script for runs its ``happy`` one. None when the Task has no script at all."""
    template = str(contract.get("template") or "")
    skill = str((contract.get("skill") or {}).get("name") or "")
    for name in dict.fromkeys(n for n in (template, skill) if n):
        for sc in dict.fromkeys((scenario, "happy")):
            if (SCRIPTS_DIR / f"{name}.{sc}.yaml").is_file():
                return f"{name}.{sc}.yaml"
    return None


def _turn_from_dict(raw: dict[str, Any]) -> ScriptedTurn:
    chunks = raw.get("stream_chunks")
    if chunks is None and raw.get("text"):
        text = str(raw["text"])
        chunks = [text[i : i + 20] for i in range(0, len(text), 20)] if text else []
    return ScriptedTurn(
        text=str(raw.get("reply_text") or raw.get("text") or ""),
        stream_chunks=[str(c) for c in (chunks or [])],
        tool_calls=list(raw.get("tool_calls") or []),
        usage=dict(raw.get("usage") or {}),
        reply_blocks=list(raw.get("reply_blocks") or []),
    )


def load_fake_script(name: str, *, attempt_n: int | None = None) -> FakeScript:
    data = yaml.safe_load(script_path(name).read_text())
    if not isinstance(data, dict):
        raise RuntimeError(f"script {name!r} must be a mapping")
    attempts_raw = data.get("attempts")
    if isinstance(attempts_raw, list) and attempts_raw:
        attempt_turns: list[list[ScriptedTurn]] = []
        for block in attempts_raw:
            if not isinstance(block, dict):
                continue
            raw = block.get("turns")
            if not isinstance(raw, list) or not raw:
                continue
            attempt_turns.append([_turn_from_dict(t) for t in raw if isinstance(t, dict)])
        if not attempt_turns:
            raise RuntimeError(f"script {name!r} attempts need non-empty turns")
        idx = max(0, int(attempt_n or 1) - 1)
        if idx >= len(attempt_turns):
            idx = len(attempt_turns) - 1
        return FakeScript(
            turns=attempt_turns[idx],
            repeat_final=bool(data.get("repeat_final")),
            attempt_turns=attempt_turns,
        )
    turns_raw = data.get("turns")
    if not isinstance(turns_raw, list) or not turns_raw:
        raise RuntimeError(f"script {name!r} needs a non-empty turns list")
    turns = [_turn_from_dict(t) for t in turns_raw if isinstance(t, dict)]
    return FakeScript(turns=turns, repeat_final=bool(data.get("repeat_final")))
