"""Run pack verifiers on task outputs (M2)."""

from __future__ import annotations

from typing import Any, Callable, Literal

from psycopg import AsyncConnection

from .worker_fence import ClaimedAttempt

Verdict = Literal["PASS", "REWORK", "FAIL"]

Handler = Callable[
    [AsyncConnection, ClaimedAttempt, dict[str, Any], dict[str, dict[str, dict]]],
    tuple[Verdict, list[str]],
]

_HANDLERS: dict[str, Handler] = {}


def register_implementation(path: str, handler: Handler) -> None:
    _HANDLERS[path] = handler


def unregister_implementation(path: str) -> None:
    _HANDLERS.pop(path, None)


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
    handler = _HANDLERS.get(str(impl))
    if handler is None:
        # Fail closed: a verifier that can't run never passes work.
        return "FAIL", [f"Verifier {verifier_name!r} has no implementation available ({impl!r})."]
    return handler(conn, gate, result, defs)
