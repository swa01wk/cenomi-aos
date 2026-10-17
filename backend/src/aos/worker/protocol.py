"""The worker protocol: how an agent-worker claims, works on and finishes one Task attempt.

The worker holds no credentials and no database access. Every command carries the attempt id
and its fencing token; the kernel rejects any command whose token is not the current one, so a
worker that stalled and lost its lease can never commit late work (reference architecture 19.4).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


class Fenced(Exception):
    """The kernel answered 409 FENCED: another attempt owns this Task now. Stop without effects."""


@dataclass(frozen=True)
class Attempt:
    attempt_id: str
    task_id: str
    fencing_token: int
    lease_seconds: float
    contract: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Submission:
    expected_task_version: int
    input_artifact_digests: dict[str, str]
    result_artifact_ids: list[str]
    summary: str = ""


class KernelClient(Protocol):
    """What the worker may ask of the kernel. Implemented over HTTP in production, in memory in tests."""

    def claim(self, worker_id: str, lanes: list[str]) -> Attempt | None: ...

    def heartbeat(self, attempt: Attempt) -> None: ...

    def event(self, attempt: Attempt, kind: str, data: dict[str, Any]) -> None: ...

    def submit(self, attempt: Attempt, submission: Submission) -> dict[str, Any]: ...

    def fail(self, attempt: Attempt, failure_class: str, message: str) -> None: ...
