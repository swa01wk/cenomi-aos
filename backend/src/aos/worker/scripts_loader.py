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


def load_fake_script(name: str) -> FakeScript:
    data = yaml.safe_load(script_path(name).read_text())
    if not isinstance(data, dict):
        raise RuntimeError(f"script {name!r} must be a mapping")
    turns_raw = data.get("turns")
    if not isinstance(turns_raw, list) or not turns_raw:
        raise RuntimeError(f"script {name!r} needs a non-empty turns list")
    turns = [_turn_from_dict(t) for t in turns_raw if isinstance(t, dict)]
    return FakeScript(turns=turns, repeat_final=bool(data.get("repeat_final")))
