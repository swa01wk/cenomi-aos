"""Pick seat and workflow for a free-text request from pack-declared intake hints."""

from __future__ import annotations

import re
from typing import Any

_TOKEN = re.compile(r"[a-z0-9']+")


def _hint_score(message: str, hints: list[str]) -> int:
    if not hints:
        return 0
    lower = message.lower()
    tokens = set(_TOKEN.findall(lower))
    score = 0
    for raw in hints:
        hint = raw.lower().strip()
        if not hint:
            continue
        if " " in hint:
            if hint in lower:
                score += 2
        elif hint in tokens or hint in lower:
            score += 1
    return score


def _text_field_score(message: str, *fields: str) -> int:
    lower = message.lower()
    tokens = set(_TOKEN.findall(lower))
    score = 0
    for field in fields:
        for word in _TOKEN.findall(field.lower()):
            if len(word) < 3:
                continue
            if word in tokens or word in lower:
                score += 1
    return score


def route_intake_message(message: str, workers: list[dict[str, Any]]) -> tuple[str, str]:
    """Return (seat_name, workflow_name) for the best-matching published route."""
    best: tuple[str, str] | None = None
    best_score = -1
    for worker in workers:
        seat = str(worker["seat"])
        for wf in worker.get("workflows") or []:
            wname = str(wf["name"])
            hints = wf.get("intake_hints") or []
            if not hints:
                continue
            score = _hint_score(message, hints if isinstance(hints, list) else [])
            score += _text_field_score(message, str(wf.get("title") or ""), str(wf.get("description") or ""))
            key = (seat, wname)
            if score > best_score or (score == best_score and best is not None and key < best):
                best_score = score
                best = key
            elif best is None:
                best = key
                best_score = score
    if best is None:
        for worker in workers:
            seat = str(worker["seat"])
            for wf in worker.get("workflows") or []:
                hints = wf.get("intake_hints") or []
                if hints:
                    return seat, str(wf["name"])
        w0 = workers[0]
        wf0 = (w0.get("workflows") or [{}])[0]
        return str(w0["seat"]), str(wf0.get("name", ""))
    return best


def colleague_for_route(seat: str, workers: list[dict[str, Any]]) -> str | None:
    for worker in workers:
        if worker["seat"] == seat:
            return str(worker.get("colleague_name") or worker.get("display_name") or seat)
    return None
