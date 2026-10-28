"""Run a simulation's Task attempts through the real worker graphs, inside the simulation's transaction.

The worker normally talks to the kernel over HTTP from its own process. In a simulation both sides share the one
connection whose transaction is rolled back at the end: a kernel client calls the functions behind the worker
routes on that connection, tool calls get the same connection (their inner transactions become savepoints),
connectors are served in-process from ``aos.connectors`` with fresh in-memory data, and checkpoints stay in memory.
Nothing outside the transaction changes, and no real connector is called.

Tasks without a fake model script, and installs without the agent runtime, keep the simulation's stub.
"""

from __future__ import annotations

import importlib
import json
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from psycopg import AsyncConnection

from .gateway.broker import CredentialBroker
from .gateway.gateway import ToolGateway
from .kernel import artifacts, worker_attempts, worker_events, worker_questions, worker_submit, worker_tools
from .kernel.instances import _load_definitions
from .kernel.org import OrgModel
from .kernel.refusal import CommittedRefusal
from .kernel.worker_fence import CommittedFenced, WorkerFenceError, require_claimed_attempt

WORKER_ID = "simulate-worker"
LEASE_SECONDS = 300.0
_KERNEL_ERRORS = (worker_attempts.WorkerError, WorkerFenceError, artifacts.ArtifactError)


class _OneConnection:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    @asynccontextmanager
    async def connection(self):  # type: ignore[no-untyped-def]
        yield self._conn


class _NoHub:
    async def publish_delta(self, *args: Any, **kwargs: Any) -> None:
        return None


def _in_process_connectors(connector_secrets: dict[str, str]):  # type: ignore[no-untyped-def]
    from mcp.client.client import Client

    from .connectors.base import ConnectorConfig

    servers: dict[str, Any] = {}

    async def invoke(*, connector: str, tool: str, arguments: dict[str, Any]) -> Any:
        if connector not in servers:
            module = importlib.import_module(f"{__package__}.connectors.{connector}")
            servers[connector], _store = module.build_server(
                ConnectorConfig(name=connector, secret=connector_secrets.get(connector))
            )
        async with Client(servers[connector]) as client:
            return await client.call_tool(tool, arguments)

    return invoke


class InProcessKernel:
    """The worker's KernelClient over the simulation's connection, claiming one given attempt."""

    def __init__(
        self,
        conn: AsyncConnection,
        *,
        org: OrgModel,
        org_id: str,
        packs_dir: Path,
        attempt_id: str,
        connector_names: list[str],
    ) -> None:
        self._conn = conn
        self._org = org
        self._org_id = org_id
        self._packs_dir = packs_dir
        self._attempt_id = attempt_id
        connector_secrets = {name: secrets.token_hex(16) for name in connector_names}
        self._broker = CredentialBroker(connector_secrets)
        self._gateway = ToolGateway(connector_urls={}, invoke_hook=_in_process_connectors(connector_secrets))

    def _fence(self, attempt: dict[str, Any]) -> dict[str, Any]:
        return {
            "org_id": self._org_id,
            "attempt_id": attempt["attempt_id"],
            "worker_id": WORKER_ID,
            "fencing_token": int(attempt["fencing_token"]),
        }

    @staticmethod
    def _problem(code: str, status: int, title: str, detail: str, extra: dict[str, Any] | None = None) -> Exception:
        from .worker.errors import BudgetExhausted, Fenced, KernelProblemError, ValidationFailed

        if status == 409 and code == "fenced":
            return Fenced(title)
        if status == 429 and code == "budget_exhausted":
            return BudgetExhausted(code, status, title, detail)
        if status == 422 and code == "validation_failed":
            err = ValidationFailed(code, status, title, detail)
            err.errors = (extra or {}).get("errors")
            return err
        return KernelProblemError(code, status, title, detail)

    def _checked(self, result: Any) -> Any:
        from .worker.errors import Fenced

        if isinstance(result, CommittedFenced):
            raise Fenced(self._attempt_id)
        if isinstance(result, CommittedRefusal):
            raise self._problem(result.code, result.status, result.title, result.detail)
        return result

    async def _call(self, coro) -> Any:  # type: ignore[no-untyped-def]
        try:
            return self._checked(await coro)
        except _KERNEL_ERRORS as exc:
            raise self._problem(exc.code, exc.status, exc.title, exc.detail, exc.extra) from exc

    async def claim(self, worker_id: str, lanes: list[str]) -> dict[str, Any] | None:
        return await worker_attempts.claim_next_attempt(
            self._conn,
            org_id=self._org_id,
            worker_id=WORKER_ID,
            lanes=lanes,
            lease_seconds=LEASE_SECONDS,
            attempt_id=self._attempt_id,
        )

    async def heartbeat(self, attempt: dict[str, Any]) -> dict[str, Any]:
        return {}

    async def get_contract(self, attempt: dict[str, Any]) -> dict[str, Any]:
        return await self._call(
            worker_attempts.get_contract(self._conn, **self._fence(attempt), packs_dir=self._packs_dir)
        )

    async def assemble_context(self, attempt: dict[str, Any], *, reason: str) -> dict[str, Any]:
        return await self._call(
            worker_attempts.assemble_context(
                self._conn,
                **self._fence(attempt),
                refresh_reason=reason,
                packs_dir=self._packs_dir,
                org=self._org,
            )
        )

    async def post_events(
        self,
        attempt: dict[str, Any],
        *,
        events: list[dict[str, Any]] | None = None,
        stream: list[dict[str, Any]] | None = None,
    ) -> None:
        from .worker.errors import Fenced

        result = await self._call(
            worker_events.post_attempt_events(
                self._conn, **self._fence(attempt), events=events, stream=stream, hub=_NoHub(), org=self._org
            )
        )
        if isinstance(result, worker_attempts.EndAttemptResult) and result.fenced is not None:
            raise Fenced(self._attempt_id)

    async def call_tool(self, attempt: dict[str, Any], tool: str, args: dict[str, Any]) -> dict[str, Any]:
        from .worker.errors import Fenced, ToolInvocationError

        try:
            result = await worker_tools.call_tool(
                _OneConnection(self._conn),
                **self._fence(attempt),
                tool=tool,
                args=args,
                broker=self._broker,
                gateway=self._gateway,
            )
        except _KERNEL_ERRORS as exc:
            raise ToolInvocationError(
                exc.detail or exc.title, code=exc.code, effect_unknown=False, errors=exc.extra.get("errors")
            ) from exc
        if isinstance(result, CommittedFenced):
            raise Fenced(self._attempt_id)
        if isinstance(result, CommittedRefusal):
            raise ToolInvocationError(
                result.detail or result.title,
                code=result.code,
                effect_unknown=False,
                rule=result.rule,
                decision_id=result.decision_id,
            )
        if isinstance(result, worker_tools.CommittedConnectorFailure):
            raise ToolInvocationError(
                result.detail, code="connector_failed", effect_unknown=False, timed_out=result.timed_out
            )
        return result

    async def save_draft(self, attempt: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
        async def save() -> Any:
            gate = await require_claimed_attempt(self._conn, **self._fence(attempt))
            if isinstance(gate, CommittedFenced):
                return gate
            cur = await self._conn.execute(
                "select pack_version_id from work.instances where id = %s", (gate.instance_id,)
            )
            defs = await _load_definitions(self._conn, str((await cur.fetchone())[0]))
            return await artifacts.save_draft_from_attempt(
                self._conn, org=self._org, gate=gate, body=body, defs=defs, packs_dir=self._packs_dir
            )

        return await self._call(save())

    async def ask_questions(
        self,
        attempt: dict[str, Any],
        *,
        blocks: list[dict[str, Any]],
        questions: list[str] | None = None,
    ) -> dict[str, Any]:
        return await self._call(
            worker_questions.ask_questions(self._conn, **self._fence(attempt), blocks=blocks, questions=questions)
        )

    async def submit_result(self, attempt: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        return await self._call(
            worker_submit.submit_result(
                self._conn, org=self._org, **self._fence(attempt), result=dict(result), packs_dir=self._packs_dir
            )
        )

    async def fail_attempt(self, attempt: dict[str, Any], failure_class: str, message: str) -> None:
        from .worker.errors import Fenced

        try:
            result = await worker_attempts.fail_attempt(
                self._conn,
                org=self._org,
                **self._fence(attempt),
                failure_class=failure_class,
                message=message,
            )
        except WorkerFenceError as exc:
            raise Fenced(self._attempt_id) from exc
        if not result.ended and result.fenced is not None:
            raise Fenced(self._attempt_id)


def runtime_available() -> bool:
    try:
        importlib.import_module("langgraph.checkpoint.memory")
        importlib.import_module(f"{__package__}.worker.runtime")
    except ImportError:
        return False
    return True


async def run_attempt(
    conn: AsyncConnection,
    *,
    org: OrgModel,
    org_id: str,
    packs_dir: Path,
    attempt_id: str,
) -> str | None:
    """Run one admitted attempt through its graph with the fake model; None when the stub should run it instead."""
    cur = await conn.execute(
        "select t.kind, t.contract, i.pack_version_id from work.attempts a join work.tasks t on t.id = a.task_id"
        " join work.instances i on i.id = t.instance_id where a.id = %s",
        (attempt_id,),
    )
    row = await cur.fetchone()
    if row is None or str(row[0]) != "task" or not runtime_available():
        return None
    from .worker.scripts_loader import task_script

    contract = row[1] if isinstance(row[1], dict) else json.loads(row[1] or "{}")
    if task_script(contract) is None:
        return None
    from .worker.checkpointer import CheckpointerHandle
    from .worker.runner import Worker
    from .worker.runtime import FakeRuntime

    defs = await _load_definitions(conn, str(row[2]))
    kernel = InProcessKernel(
        conn,
        org=org,
        org_id=org_id,
        packs_dir=packs_dir,
        attempt_id=attempt_id,
        connector_names=sorted((defs.get("ToolProvider") or {}).keys()),
    )
    runtime = FakeRuntime(checkpointer=CheckpointerHandle.in_memory())
    worker = Worker(WORKER_ID, kernel, runtime, ("task",), heartbeat_enabled=False)  # type: ignore[arg-type]
    return await worker.run_once()
