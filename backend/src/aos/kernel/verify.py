"""Run pack verifiers on task outputs (M2)."""

from __future__ import annotations

import importlib
import inspect
from typing import Any, Awaitable, Callable, Literal

from psycopg import AsyncConnection

from .worker_fence import ClaimedAttempt

Verdict = Literal["PASS", "REWORK", "FAIL"]

Handler = Callable[
    [AsyncConnection, ClaimedAttempt, dict[str, Any], dict[str, dict[str, dict]]],
    "tuple[Verdict, list[str]] | Awaitable[tuple[Verdict, list[str]]]",
]

# Only pack extensions shipped with the kernel may run; a pack can't point the kernel at arbitrary code.
IMPLEMENTATION_PREFIX = "aos.verifiers."

_HANDLERS: dict[str, Handler] = {}


def register_implementation(path: str, handler: Handler) -> None:
    _HANDLERS[path] = handler


def unregister_implementation(path: str) -> None:
    _HANDLERS.pop(path, None)


def _handler_for(impl: str) -> Handler | None:
    if impl in _HANDLERS:
        return _HANDLERS[impl]
    if not impl.startswith(IMPLEMENTATION_PREFIX) or impl.startswith(IMPLEMENTATION_PREFIX + "_"):
        return None
    try:
        module = importlib.import_module(impl)
    except ImportError:
        return None
    handler = getattr(module, "verify", None)
    return handler if callable(handler) else None


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
    handler = _handler_for(str(impl))
    if handler is None:
        # Fail closed: a verifier that can't run never passes work.
        return "FAIL", [f"Verifier {verifier_name!r} has no implementation available ({impl!r})."]
    outcome = handler(conn, gate, result, defs)
    if inspect.isawaitable(outcome):
        outcome = await outcome
    verdict, findings = outcome
    return verdict, list(findings)
