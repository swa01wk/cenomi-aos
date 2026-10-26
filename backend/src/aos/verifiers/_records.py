"""Reads shared by the rule verifiers: the submitted outputs and the Task's own tool observations."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from psycopg import AsyncConnection


@dataclass(frozen=True)
class Output:
    artifact_id: str
    artifact_type: str
    version: int
    content: dict[str, Any]


def _doc(raw: Any) -> Any:
    return json.loads(raw) if isinstance(raw, str) else raw


async def outputs(conn: AsyncConnection, result: dict[str, Any]) -> list[Output]:
    out: list[Output] = []
    for ref in result.get("output_artifact_refs") or []:
        cur = await conn.execute(
            "select a.artifact_type, v.content from work.artifact_versions v"
            " join work.artifacts a on a.id = v.artifact_id where v.artifact_id = %s and v.version = %s",
            (ref["artifact_id"], int(ref["version"])),
        )
        row = await cur.fetchone()
        if row is not None:
            out.append(Output(str(ref["artifact_id"]), str(row[0]), int(ref["version"]), _doc(row[1]) or {}))
    return out


async def observations(conn: AsyncConnection, task_id: str) -> list[dict[str, Any]]:
    """Tool results of every attempt of this Task, oldest first."""
    cur = await conn.execute(
        "select tool_observations from work.attempts where task_id = %s order by n",
        (task_id,),
    )
    obs: list[dict[str, Any]] = []
    for (raw,) in await cur.fetchall():
        obs.extend(o for o in (_doc(raw) or []) if isinstance(o, dict))
    return obs


def items(observation: dict[str, Any]) -> list[dict[str, Any]]:
    content = observation.get("content")
    rows = content.get("items") if isinstance(content, dict) else None
    return [r for r in rows or [] if isinstance(r, dict)]
