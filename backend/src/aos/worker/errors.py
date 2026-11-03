"""HTTP and protocol errors seen by the worker runtime."""

from __future__ import annotations

from typing import Any


class Fenced(Exception):
    """409 fenced — stop this attempt without further kernel calls."""


class AttemptWaitingForInput(Exception):
    """askQuestions ended the attempt; the runner must not submit."""


class AuthFailed(Exception):
    """401 — bad or expired worker token; the process must exit."""


class KernelProblemError(Exception):
    def __init__(self, code: str, status: int, title: str, detail: str = "") -> None:
        self.code = code
        self.status = status
        self.title = title
        self.detail = detail
        super().__init__(title)


class BudgetExhausted(KernelProblemError):
    """429 budget_exhausted — attempt may already be ended by the kernel."""


class ValidationFailed(KernelProblemError):
    def __init__(
        self,
        code: str,
        status: int,
        title: str,
        detail: str = "",
        *,
        errors: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(code, status, title, detail)
        self.errors = errors


class TransientKernelError(Exception):
    """Network or 5xx after retries on an idempotent call."""


class KernelTransportError(Exception):
    """Network failure on a non-idempotent worker call (e.g. saveDraft)."""


class ToolInvocationError(Exception):
    """Tool call failed; runtime turns this into a tool observation."""

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        effect_unknown: bool = False,
        timed_out: bool = False,
        rule: str | None = None,
        decision_id: str | None = None,
        errors: list[dict[str, Any]] | None = None,
    ) -> None:
        self.message = message
        self.code = code
        self.effect_unknown = effect_unknown
        self.timed_out = timed_out
        self.rule = rule
        self.decision_id = decision_id
        self.errors = errors
        super().__init__(message)

    def __str__(self) -> str:
        return self.message
