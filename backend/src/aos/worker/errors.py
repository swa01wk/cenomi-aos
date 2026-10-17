"""HTTP and protocol errors seen by the worker runtime."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class Fenced(Exception):
    """409 fenced — stop this attempt without further kernel calls."""


class AuthFailed(Exception):
    """401 — bad or expired worker token; the process must exit."""


@dataclass(frozen=True)
class KernelProblemError(Exception):
    code: str
    status: int
    title: str
    detail: str = ""

    def __str__(self) -> str:
        return self.title


class BudgetExhausted(KernelProblemError):
    """429 budget_exhausted — attempt may already be ended by the kernel."""


class ValidationFailed(KernelProblemError):
    errors: list[dict[str, Any]] | None = None


class TransientKernelError(Exception):
    """Network or 5xx after retries on an idempotent call."""


class KernelTransportError(Exception):
    """Network failure on a non-idempotent worker call (e.g. saveDraft)."""


@dataclass
class ToolInvocationError(Exception):
    """Tool call failed; runtime turns this into a tool observation."""

    message: str
    code: str | None = None
    effect_unknown: bool = False

    def __str__(self) -> str:
        return self.message
