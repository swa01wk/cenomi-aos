"""HTTP KernelClient for the M1 worker API surface."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from .errors import (
    AuthFailed,
    BudgetExhausted,
    Fenced,
    KernelProblemError,
    KernelTransportError,
    ToolInvocationError,
    TransientKernelError,
    ValidationFailed,
)
from .types import AgentResult, SubmitResponse, WorkerAttempt

log = logging.getLogger("aos.worker.client")


class HttpKernelClient:
    def __init__(self, base_url: str, token: str, *, client: httpx.AsyncClient | None = None):
        self._base = base_url.rstrip("/")
        self._token = token
        self._client = client
        self._owned_client: httpx.AsyncClient | None = None
        self.heartbeat_count = 0

    async def aclose(self) -> None:
        if self._owned_client is not None:
            await self._owned_client.aclose()
            self._owned_client = None

    def _headers(self, fencing_token: int | None = None) -> dict[str, str]:
        h = {"Authorization": f"Bearer {self._token}"}
        if fencing_token is not None:
            h["X-AOS-Fencing-Token"] = str(fencing_token)
        return h

    async def _client_or_create(self) -> httpx.AsyncClient:
        if self._client is not None:
            return self._client
        if self._owned_client is None:
            self._owned_client = httpx.AsyncClient(timeout=httpx.Timeout(60.0))
        return self._owned_client

    def _problem(self, resp: httpx.Response) -> KernelProblemError:
        try:
            body = resp.json()
        except Exception:
            body = {}
        code = str(body.get("code") or "internal")
        title = str(body.get("title") or resp.reason_phrase)
        detail = str(body.get("detail") or "")
        if resp.status_code == 429 and code == "budget_exhausted":
            return BudgetExhausted(code, resp.status_code, title, detail)
        if resp.status_code == 422 and code == "validation_failed":
            err = ValidationFailed(code, resp.status_code, title, detail)
            err.errors = body.get("errors")
            return err
        return KernelProblemError(code, resp.status_code, title, detail)

    @staticmethod
    def _response_body(resp: httpx.Response) -> dict[str, Any]:
        try:
            body = resp.json()
        except Exception:
            return {}
        return body if isinstance(body, dict) else {}

    def _tool_invocation_error(self, resp: httpx.Response, prob: KernelProblemError) -> ToolInvocationError:
        body = self._response_body(resp)
        raw_errors = body.get("errors")
        errors: list[dict[str, Any]] | None = raw_errors if isinstance(raw_errors, list) else None
        if isinstance(prob, ValidationFailed) and prob.errors is not None:
            errors = prob.errors
        rule = body.get("rule")
        decision_id = body.get("decision_id")
        timed_out = body.get("timed_out") is True
        return ToolInvocationError(
            prob.detail or prob.title,
            code=prob.code,
            effect_unknown=False,
            timed_out=timed_out,
            rule=rule if isinstance(rule, str) else None,
            decision_id=decision_id if isinstance(decision_id, str) else None,
            errors=errors,
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        idempotent: bool,
        fencing_token: int | None = None,
        json_body: Any | None = None,
        tool_error: bool = False,
        timeout_s: float | None = None,
    ) -> httpx.Response:
        url = f"{self._base}{path}"
        headers = self._headers(fencing_token)
        delays = (0.5, 1.0, 2.0)
        last_exc: Exception | None = None
        for attempt, delay in enumerate((0.0, *delays)):
            if delay:
                await asyncio.sleep(delay)
            try:
                client = await self._client_or_create()
                resp = await client.request(
                    method,
                    url,
                    headers=headers,
                    json=json_body,
                    timeout=timeout_s,
                )
            except httpx.HTTPError as exc:
                last_exc = exc
                if not idempotent or attempt >= len(delays):
                    if tool_error:
                        raise ToolInvocationError(str(exc), effect_unknown=True) from exc
                    raise KernelTransportError(str(exc)) from exc
                continue
            if resp.status_code == 401:
                raise AuthFailed("worker token rejected")
            if resp.status_code == 409:
                try:
                    code = resp.json().get("code")
                except Exception:
                    code = None
                if code == "fenced":
                    raise Fenced(path)
            if resp.status_code == 429:
                prob = self._problem(resp)
                raise prob
            if tool_error and resp.status_code == 502:
                prob = self._problem(resp)
                if prob.code == "connector_failed":
                    raise self._tool_invocation_error(resp, prob)
            if resp.status_code >= 500:
                last_exc = TransientKernelError(f"{resp.status_code} from kernel")
                if idempotent and attempt < len(delays):
                    continue
                if tool_error:
                    raise ToolInvocationError(
                        f"kernel {resp.status_code}",
                        code="unavailable",
                        effect_unknown=True,
                    ) from last_exc
                raise last_exc
            if resp.status_code >= 400:
                prob = self._problem(resp)
                if tool_error:
                    raise self._tool_invocation_error(resp, prob)
                raise prob
            return resp
        assert last_exc is not None
        raise last_exc

    async def claim(self, worker_id: str, lanes: list[str]) -> WorkerAttempt | None:
        resp = await self._request(
            "POST",
            "/worker/attempts/claim",
            idempotent=False,
            json_body={"worker_id": worker_id, "lanes": lanes},
        )
        if resp.status_code == 204:
            return None
        return resp.json()

    async def heartbeat(self, attempt: WorkerAttempt) -> dict[str, Any]:
        self.heartbeat_count += 1
        lease = float(attempt["lease_seconds"])
        timeout_s = max(0.1, lease / 3.0)
        resp = await self._request(
            "POST",
            f"/worker/attempts/{attempt['attempt_id']}/heartbeat",
            idempotent=True,
            fencing_token=attempt["fencing_token"],
            timeout_s=timeout_s,
        )
        return resp.json()

    async def get_contract(self, attempt: WorkerAttempt) -> dict[str, Any]:
        resp = await self._request(
            "GET",
            f"/worker/attempts/{attempt['attempt_id']}/contract",
            idempotent=True,
            fencing_token=attempt["fencing_token"],
        )
        return resp.json()

    async def assemble_context(self, attempt: WorkerAttempt, *, reason: str) -> dict[str, Any]:
        resp = await self._request(
            "POST",
            f"/worker/attempts/{attempt['attempt_id']}/context",
            idempotent=False,
            fencing_token=attempt["fencing_token"],
            json_body={"reason": reason},
        )
        return resp.json()

    async def post_events(
        self,
        attempt: WorkerAttempt,
        *,
        events: list[dict[str, Any]] | None = None,
        stream: list[dict[str, Any]] | None = None,
    ) -> None:
        body: dict[str, Any] = {}
        if events is not None:
            body["events"] = events
        if stream is not None:
            body["stream"] = stream
        await self._request(
            "POST",
            f"/worker/attempts/{attempt['attempt_id']}/events",
            idempotent=False,
            fencing_token=attempt["fencing_token"],
            json_body=body,
        )

    async def call_tool(self, attempt: WorkerAttempt, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        resp = await self._request(
            "POST",
            f"/worker/attempts/{attempt['attempt_id']}/tools/{tool}",
            idempotent=False,
            fencing_token=attempt["fencing_token"],
            json_body={"args": args},
            tool_error=True,
        )
        return resp.json()

    async def save_draft(self, attempt: WorkerAttempt, body: dict[str, Any]) -> dict[str, Any]:
        resp = await self._request(
            "POST",
            f"/worker/attempts/{attempt['attempt_id']}/drafts",
            idempotent=False,
            fencing_token=attempt["fencing_token"],
            json_body=body,
        )
        return resp.json()

    async def ask_questions(
        self,
        attempt: WorkerAttempt,
        *,
        blocks: list[dict[str, Any]],
        questions: list[str] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"blocks": blocks}
        if questions is not None:
            body["questions"] = questions
        resp = await self._request(
            "POST",
            f"/worker/attempts/{attempt['attempt_id']}/questions",
            idempotent=False,
            fencing_token=attempt["fencing_token"],
            json_body=body,
        )
        return resp.json()

    async def submit_result(self, attempt: WorkerAttempt, result: AgentResult) -> SubmitResponse:
        resp = await self._request(
            "POST",
            f"/worker/attempts/{attempt['attempt_id']}/submit",
            idempotent=True,
            fencing_token=attempt["fencing_token"],
            json_body=dict(result),
        )
        return resp.json()

    async def fail_attempt(self, attempt: WorkerAttempt, failure_class: str, message: str) -> None:
        await self._request(
            "POST",
            f"/worker/attempts/{attempt['attempt_id']}/fail",
            idempotent=False,
            fencing_token=attempt["fencing_token"],
            json_body={"failure_class": failure_class, "message": message},
        )
