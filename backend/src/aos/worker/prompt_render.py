"""Render assist_v1: trusted system text vs per-step context message."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .models import PROMPT_VERSION_ASSIST
from .untrusted import format_observation_for_context, wrap_untrusted

_PROMPTS = Path(__file__).resolve().parent / "prompts"


@lru_cache(maxsize=1)
def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(_PROMPTS)),
        autoescape=select_autoescape(default_for_string=False),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def _expected_outputs_text(contract: dict[str, Any]) -> str:
    lines: list[str] = []
    for out in contract.get("expected_outputs") or []:
        if not isinstance(out, dict):
            continue
        name = out.get("artifact_type") or out.get("name") or "output"
        fields = out.get("fields") or []
        lines.append(f"- {name}: {json.dumps(fields, sort_keys=True)}")
    return "\n".join(lines)


def render_system_message(*, contract: dict[str, Any], skill_instructions: str, envelope: dict[str, Any]) -> str:
    scope = envelope.get("scope") if isinstance(envelope.get("scope"), dict) else {}
    org_id = str(scope.get("org_id") or "the organization")
    seat = str(scope.get("seat") or "digital worker")
    tmpl = _env().get_template("assist_v1.jinja")
    return tmpl.render(
        org_id=org_id,
        seat_label=seat,
        skill_instructions=skill_instructions,
        objective=str(contract.get("objective") or envelope.get("objective") or ""),
        expected_outputs=_expected_outputs_text(contract),
        constraints=list(envelope.get("constraints") or []),
    ).strip()


def render_context_message(
    *, envelope: dict[str, Any], worker_notes: list[str], actions_this_reply: list[str] | None = None
) -> str:
    """Envelope snapshot for one model step; untrusted observations wrapped; worker_notes never in system."""
    resolvers = envelope.get("resolvers") if isinstance(envelope.get("resolvers"), dict) else {}
    observations = envelope.get("tool_observations") if isinstance(envelope.get("tool_observations"), list) else []
    obs_lines = [format_observation_for_context(o) for o in observations if isinstance(o, dict)]
    notes = [wrap_untrusted(n, source="worker") for n in worker_notes]
    payload = {
        "job_snapshot": resolvers.get("job_snapshot"),
        "running_summary": resolvers.get("running_summary"),
        "recent_messages": resolvers.get("recent_messages"),
        "artifacts": envelope.get("artifacts"),
        "tool_observations_rendered": obs_lines,
        "worker_notes": notes,
        "your_actions_this_reply": list(actions_this_reply or []),
        "remaining_budget": envelope.get("remaining_budget"),
        "redactions": envelope.get("redactions"),
    }
    return json.dumps(payload, sort_keys=True, ensure_ascii=False)


def prompt_version() -> str:
    return PROMPT_VERSION_ASSIST
