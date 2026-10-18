"""RFC 9457 problem responses for kernel errors."""

from __future__ import annotations

import re
import secrets
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

_ALLOWED_EXTRA = frozenset({"trace_id", "decision_id", "rule", "current_version", "errors", "timed_out"})


class KernelProblem(Exception):
    def __init__(
        self,
        code: str,
        status: int,
        title: str,
        detail: str = "",
        *,
        instance: str | None = None,
        **extra: Any,
    ) -> None:
        bad = set(extra) - _ALLOWED_EXTRA
        if bad:
            raise ValueError(f"unsupported Problem fields: {sorted(bad)}")
        self.code = code
        self.status = status
        self.title = title
        self.detail = detail
        self.instance = instance
        self.extra = extra
        super().__init__(title)


def trace_id_from_request(request: Request) -> str:
    for header in ("traceparent", "x-trace-id", "x-request-id"):
        raw = request.headers.get(header)
        if not raw:
            continue
        if header == "traceparent":
            m = re.match(r"00-([0-9a-f]{32})-", raw.strip(), re.I)
            if m:
                return m.group(1).lower()
        token = raw.strip().lower()
        if re.fullmatch(r"[0-9a-f]{32}", token):
            return token
    return secrets.token_hex(16)


def problem_body(exc: KernelProblem, *, trace_id: str) -> dict[str, Any]:
    body: dict[str, Any] = {
        "type": f"https://aos.local/problems/{exc.code}",
        "title": exc.title,
        "status": exc.status,
        "code": exc.code,
        "trace_id": trace_id,
    }
    if exc.detail:
        body["detail"] = exc.detail
    if exc.instance:
        body["instance"] = exc.instance
    body.update(exc.extra)
    return body


def problem_response(request: Request, problem: KernelProblem) -> JSONResponse:
    return JSONResponse(
        problem_body(problem, trace_id=trace_id_from_request(request)),
        status_code=problem.status,
        media_type="application/problem+json",
    )


async def kernel_problem_handler(request: Request, exc: KernelProblem) -> JSONResponse:
    return problem_response(request, exc)


def register_problem_handlers(app: FastAPI) -> None:
    app.add_exception_handler(KernelProblem, kernel_problem_handler)
