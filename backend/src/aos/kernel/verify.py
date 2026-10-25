"""Run pack verifiers on task outputs (M2)."""

from __future__ import annotations

import importlib
import json
from typing import Any, Callable, Literal

from psycopg import AsyncConnection

from . import clock
from .artifacts import parse_artifact_type
from .worker_fence import ClaimedAttempt

Verdict = Literal["PASS", "REWORK", "FAIL"]

PureHandler = Callable[[dict[str, Any]], tuple[Verdict, list[str]]]

_HANDLERS: dict[str, PureHandler] = {}

_ALLOWED_PREFIX = "aos.verifiers."


def register_implementation(path: str, handler: PureHandler) -> None:
    _HANDLERS[path] = handler


def unregister_implementation(path: str) -> None:
    _HANDLERS.pop(path, None)


def _implementation_allowed(path: str) -> bool:
    if not path.startswith(_ALLOWED_PREFIX):
        return False
    rest = path[len(_ALLOWED_PREFIX) :]
    if not rest or ".." in path or rest.startswith("."):
        return False
    return all(part.isidentifier() for part in rest.split("."))


def _load_handler(path: str) -> PureHandler | None:
    registered = _HANDLERS.get(path)
    if registered is not None:
        return registered
    if not _implementation_allowed(path):
        return None
    try:
        mod = importlib.import_module(path)
    except ImportError:
        return None
    fn = getattr(mod, "verify", None)
    if not callable(fn):
        return None
    return fn  # type: ignore[return-value]


def _artifact_type_map(defs: dict[str, dict[str, dict]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for name, raw in (defs.get("ArtifactType") or {}).items():
        at = parse_artifact_type(defs, name)
        spec = at.spec
        fields: dict[str, Any] = {}
        for fname, fspec in spec.fields.items():
            fields[fname] = {
                "type": fspec.type,
                "classification": fspec.classification or spec.classification,
                "required": fspec.required,
            }
        out[name] = {
            "fields": fields,
            "classification": spec.classification,
            "row_key": spec.row_key,
            "row_based": spec.row_based,
        }
    return out


async def _load_output_versions(
    conn: AsyncConnection,
    *,
    instance_id: str,
    refs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    outputs: list[dict[str, Any]] = []
    for ref in refs:
        aid = ref.get("artifact_id")
        version = ref.get("version")
        if not aid or version is None:
            continue
        cur = await conn.execute(
            "select v.content, a.artifact_type"
            " from work.artifact_versions v"
            " join work.artifacts a on a.id = v.artifact_id"
            " where v.artifact_id = %s and v.version = %s and a.instance_id = %s",
            (str(aid), int(version), instance_id),
        )
        row = await cur.fetchone()
        if row is None:
            continue
        content, atype = row
        if not isinstance(content, dict):
            content = json.loads(content)
        outputs.append(
            {
                "artifact_id": str(aid),
                "artifact_type": str(atype),
                "version": int(version),
                "content": content,
            }
        )
    return outputs


async def _load_tool_receipts(
    conn: AsyncConnection,
    *,
    org_id: str,
    task_id: str,
) -> list[dict[str, Any]]:
    cur = await conn.execute(
        "select n, tool_observations from work.attempts where task_id = %s order by n",
        (task_id,),
    )
    rows = await cur.fetchall()
    receipts: list[dict[str, Any]] = []
    for attempt_n, obs in rows:
        observations = obs if isinstance(obs, list) else json.loads(obs or "[]")
        if not isinstance(observations, list):
            continue
        for entry in observations:
            if not isinstance(entry, dict):
                continue
            ref = entry.get("receipt_ref")
            content = entry.get("content")
            if ref and content is None:
                pcur = await conn.execute(
                    "select body from evidence.tool_payloads where ref = %s and org_id = %s",
                    (str(ref), org_id),
                )
                prow = await pcur.fetchone()
                if prow is not None:
                    body = prow[0]
                    content = body if isinstance(body, dict) else json.loads(body)
            receipts.append(
                {
                    "attempt_n": int(attempt_n),
                    "tool": entry.get("tool"),
                    "args": entry.get("args") if isinstance(entry.get("args"), dict) else {},
                    "receipt_ref": ref,
                    "content": content,
                }
            )
    return receipts


async def _load_instance_artifacts(
    conn: AsyncConnection,
    *,
    instance_id: str,
) -> list[dict[str, Any]]:
    cur = await conn.execute(
        "select a.id, a.artifact_type, a.latest_version, v.content"
        " from work.artifacts a"
        " join work.artifact_versions v on v.artifact_id = a.id and v.version = a.latest_version"
        " where a.instance_id = %s",
        (instance_id,),
    )
    out: list[dict[str, Any]] = []
    for aid, atype, version, content in await cur.fetchall():
        doc = content if isinstance(content, dict) else json.loads(content)
        out.append(
            {
                "artifact_id": str(aid),
                "artifact_type": str(atype),
                "version": int(version),
                "content": doc,
            }
        )
    return out


async def build_verifier_input(
    conn: AsyncConnection,
    *,
    gate: ClaimedAttempt,
    result: dict[str, Any],
    defs: dict[str, dict[str, dict]],
) -> dict[str, Any]:
    refs = result.get("output_artifact_refs") or []
    return {
        "now": clock.now(),
        "outputs": await _load_output_versions(conn, instance_id=gate.instance_id, refs=refs),
        "artifact_types": _artifact_type_map(defs),
        "tool_receipts": await _load_tool_receipts(conn, org_id=gate.org_id, task_id=gate.task_id),
        "instance_artifacts": await _load_instance_artifacts(conn, instance_id=gate.instance_id),
    }


async def run_task_verifier(
    conn: AsyncConnection,
    *,
    verifier_name: str,
    defs: dict[str, dict[str, dict]],
    gate: ClaimedAttempt,
    result: dict[str, Any],
) -> tuple[Verdict, list[str]]:
    vdoc = (defs.get("Verifier") or {}).get(verifier_name)
    if vdoc is None:
        return "FAIL", [f"Verifier {verifier_name!r} is not on the pinned pack."]
    impl = (vdoc.get("spec") or {}).get("implementation") or ""
    impl_str = str(impl)
    handler = _load_handler(impl_str)
    if handler is None:
        return "FAIL", [f"Verifier {verifier_name!r} has no implementation available ({impl_str!r})."]
    inp = await build_verifier_input(conn, gate=gate, result=result, defs=defs)
    return handler(inp)
