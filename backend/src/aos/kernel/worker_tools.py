"""callTool: authorize, gateway invoke, complete (M1-BE-07)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from jsonschema import Draft202012Validator
from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from ..gateway.broker import CredentialBroker, Grant
from ..gateway.gateway import InvokeFailure, InvokeSuccess, ToolGateway
from . import ids
from .instances import _load_definitions
from .outbox import ExecutionEventWrite, write_execution_event
from .policy_allow import evaluate_tool_authority
from .refusal import CommittedRefusal, record_tool_denied
from .worker_fence import CommittedFenced, require_claimed_attempt, write_attempt_fenced


@dataclass(frozen=True)
class AuthorizedCall:
    org_id: str
    instance_id: str
    task_id: str
    attempt_id: str
    correlation_id: str
    seat: str
    worker_id: str
    fencing_token: int
    tool: str
    grant: dict[str, Any]
    args: dict[str, Any]
    decision_id: str
    action_id: str
    broker_token: str
    usage: dict[str, Any]
    contract: dict[str, Any]


@dataclass(frozen=True)
class CommittedConnectorFailure:
    detail: str
    timed_out: bool


@dataclass(frozen=True)
class _FenceStale:
    org_id: str
    instance_id: str
    task_id: str
    correlation_id: str
    proposed_token: int
    current_token: int


def _grant_for_tool(contract: dict[str, Any], tool: str) -> dict[str, Any] | None:
    for entry in contract.get("allowed_tools") or []:
        if isinstance(entry, dict) and entry.get("name") == tool:
            return entry
    return None


def _validate_args(args: dict[str, Any], schema: dict[str, Any]) -> list[dict[str, str]] | None:
    validator = Draft202012Validator(schema)
    errors = []
    for err in sorted(validator.iter_errors(args), key=lambda e: e.path):
        pointer = "/" + "/".join(str(p) for p in err.path) if err.path else ""
        errors.append({"pointer": pointer or "/", "message": err.message})
    return errors or None


async def _authority_grants(
    conn: AsyncConnection,
    *,
    org_id: str,
    seat_name: str,
    seat_version: int,
    pack_version_id: str,
) -> tuple[list[dict[str, Any]], str, int]:
    defs = await _load_definitions(conn, pack_version_id)
    seat_doc = (defs.get("Seat") or {}).get(seat_name) or {}
    prof_ref = (seat_doc.get("spec") or {}).get("authority_profile") or ""
    prof_name, _, ver_s = prof_ref.partition("@")
    prof_ver = int(ver_s) if ver_s.isdigit() else 0
    prof = (defs.get("Policy") or {}).get(prof_name) or {}
    grants = (prof.get("spec") or {}).get("grants") or []
    return grants, prof_name, prof_ver


def _class_refusal(tool_class: str) -> tuple[str, str, str]:
    if tool_class == "committed_effect":
        return (
            "not_permitted",
            "gateway.committed_effect_use_actions",
            "Committed effects must use request_action, not callTool.",
        )
    if tool_class == "staged_write":
        return (
            "not_permitted",
            "gateway.staged_write_not_in_m1",
            "Staged-write tools are not available through callTool in this milestone.",
        )
    if tool_class == "compute":
        return (
            "not_permitted",
            "gateway.compute_not_in_m1",
            "Compute tools are not available through callTool in this milestone.",
        )
    if tool_class == "kernel":
        return (
            "not_permitted",
            "gateway.kernel_tool",
            "Kernel tools use their dedicated worker endpoints.",
        )
    if tool_class != "read":
        return ("not_permitted", "gateway.tool_class", "This tool class cannot be called here.")
    return ("not_permitted", "gateway.tool_class", "This tool cannot be called here.")


async def authorize_tool_call(
    conn: AsyncConnection,
    *,
    org_id: str,
    attempt_id: str,
    worker_id: str,
    fencing_token: int,
    tool: str,
    args: dict[str, Any],
    broker: CredentialBroker,
) -> CommittedRefusal | CommittedFenced | AuthorizedCall:
    gate = await require_claimed_attempt(
        conn, org_id=org_id, attempt_id=attempt_id, worker_id=worker_id, fencing_token=fencing_token
    )
    if isinstance(gate, CommittedFenced):
        return gate

    contract = gate.contract
    grant = _grant_for_tool(contract, tool)
    if grant is None:
        return await record_tool_denied(
            conn,
            org_id=gate.org_id,
            instance_id=gate.instance_id,
            task_id=gate.task_id,
            attempt_id=attempt_id,
            correlation_id=gate.correlation_id,
            seat=gate.seat,
            tool=tool,
            code="not_permitted",
            rule="contract.allowed_tools",
            title="Tool not allowed",
            detail="This tool is not in the task contract.",
            status=403,
        )

    tool_class = str(grant.get("class") or "")
    if tool_class != "read" or grant.get("kind") != "connector":
        code, rule, detail = _class_refusal(tool_class)
        return await record_tool_denied(
            conn,
            org_id=gate.org_id,
            instance_id=gate.instance_id,
            task_id=gate.task_id,
            attempt_id=attempt_id,
            correlation_id=gate.correlation_id,
            seat=gate.seat,
            tool=tool,
            code=code,
            rule=rule,
            title="Tool not allowed",
            detail=detail,
            status=403,
        )

    resource = str(grant.get("resource") or "")
    action = str(grant.get("action") or "")
    scope = contract.get("permission_scope") or {}
    scope_resources = list(scope.get("resources") or [])

    cur = await conn.execute(
        "select pack_version_id from work.instances where id = %s and org_id = %s",
        (gate.instance_id, org_id),
    )
    inst_row = await cur.fetchone()
    if inst_row is None:
        raise RuntimeError("instance missing during tool authorize")
    pack_version_id = str(inst_row[0])

    grants, prof_name, prof_ver = await _authority_grants(
        conn,
        org_id=org_id,
        seat_name=gate.seat,
        seat_version=gate.seat_version,
        pack_version_id=pack_version_id,
    )
    allowed, refuse_code, rule = evaluate_tool_authority(
        grants,
        resource=resource,
        action=action,
        scope_resources=scope_resources,
        profile_name=prof_name,
        profile_version=prof_ver,
    )
    if not allowed:
        status = 403
        if refuse_code == "policy_never":
            status = 403
        elif refuse_code == "budget_exhausted":
            status = 429
        return await record_tool_denied(
            conn,
            org_id=gate.org_id,
            instance_id=gate.instance_id,
            task_id=gate.task_id,
            attempt_id=attempt_id,
            correlation_id=gate.correlation_id,
            seat=gate.seat,
            tool=tool,
            code=refuse_code or "not_permitted",
            rule=rule or "authority.deny",
            title="Tool not allowed",
            detail="Policy refused this tool call.",
            status=status,
        )

    schema = grant.get("input_schema")
    if not isinstance(schema, dict):
        schema = {"type": "object"}
    field_errors = _validate_args(args, schema)
    if field_errors:
        from .worker_attempts import WorkerError

        raise WorkerError(
            "validation_failed",
            422,
            "Tool arguments are invalid",
            "Fix the arguments and try again.",
            errors=field_errors,
        )

    budget = contract.get("budget") or {}
    actions_cap = int(budget.get("actions") or 0)
    usage = dict(gate.usage)
    used_actions = int(usage.get("actions") or 0)
    if actions_cap and used_actions + 1 > actions_cap:
        return await record_tool_denied(
            conn,
            org_id=gate.org_id,
            instance_id=gate.instance_id,
            task_id=gate.task_id,
            attempt_id=attempt_id,
            correlation_id=gate.correlation_id,
            seat=gate.seat,
            tool=tool,
            code="budget_exhausted",
            rule="budget.actions",
            title="Action budget exhausted",
            detail="This attempt has no tool calls remaining.",
            status=429,
        )

    decision_id = ids.new_decision_id()
    action_id = ids.new_broker_action_id()
    connector = str(grant.get("connector") or "")
    token = broker.mint(
        Grant(
            connector=connector,
            resource=resource,
            action=action,
            action_id=action_id,
            org_id=org_id,
            tool=tool,
            attempt_id=attempt_id,
        )
    )

    usage["actions"] = used_actions + 1
    await conn.execute("update work.attempts set usage = %s where id = %s", (Jsonb(usage), attempt_id))

    await write_execution_event(
        conn,
        ExecutionEventWrite(
            org_id=gate.org_id,
            run_id=gate.instance_id,
            event_type="ToolAuthorized",
            actor_kind="seat",
            actor_id=gate.seat,
            correlation_id=gate.correlation_id,
            redacted_summary=f"{tool} authorized.",
            task_id=gate.task_id,
            attempt_id=attempt_id,
            attributes={"tool": tool, "decision_id": decision_id, "action_id": action_id},
        ),
    )

    return AuthorizedCall(
        org_id=gate.org_id,
        instance_id=gate.instance_id,
        task_id=gate.task_id,
        attempt_id=attempt_id,
        correlation_id=gate.correlation_id,
        seat=gate.seat,
        worker_id=worker_id,
        fencing_token=fencing_token,
        tool=tool,
        grant=grant,
        args=args,
        decision_id=decision_id,
        action_id=action_id,
        broker_token=token,
        usage=usage,
        contract=contract,
    )


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


async def _store_payload(conn: AsyncConnection, *, org_id: str, body: Any) -> str:
    ref = ids.new_tool_payload_ref()
    payload_bytes = _canonical_json(body)
    content_hash = hashlib.sha256(payload_bytes).hexdigest()
    await conn.execute(
        "insert into evidence.tool_payloads (ref, org_id, content_hash, body) values (%s, %s, %s, %s)",
        (ref, org_id, content_hash, Jsonb(body)),
    )
    return ref


async def _fence_stale(
    conn: AsyncConnection,
    *,
    org_id: str,
    attempt_id: str,
    worker_id: str,
    fencing_token: int,
) -> _FenceStale | None:
    cur = await conn.execute(
        "select a.state, a.worker_id, a.fencing_token, t.fencing_token, t.id, t.instance_id, i.org_id, i.correlation_id"
        " from work.attempts a"
        " join work.tasks t on t.id = a.task_id"
        " join work.instances i on i.id = t.instance_id"
        " where a.id = %s and i.org_id = %s"
        " for update of a, t",
        (attempt_id, org_id),
    )
    row = await cur.fetchone()
    if row is None:
        raise RuntimeError("attempt missing during tool complete")
    a_state, a_worker, a_token, task_token, task_id, instance_id, row_org, correlation_id = row
    current = int(task_token)
    ok = (
        a_state == "CLAIMED"
        and a_worker == worker_id
        and fencing_token == current
        and int(a_token) == current
    )
    if ok:
        return None
    return _FenceStale(
        str(row_org),
        instance_id,
        task_id,
        correlation_id,
        int(fencing_token),
        current,
    )


async def complete_tool_call(
    conn: AsyncConnection,
    *,
    org_id: str,
    authorized: AuthorizedCall,
    invoke: InvokeSuccess | InvokeFailure,
    fencing_token: int,
) -> dict[str, Any] | CommittedFenced | CommittedConnectorFailure:
    duration_ms = invoke.duration_ms if isinstance(invoke, (InvokeSuccess, InvokeFailure)) else 0

    async def _tool_completed(outcome: str, receipt_ref: str | None, summary: str) -> None:
        await write_execution_event(
            conn,
            ExecutionEventWrite(
                org_id=authorized.org_id,
                run_id=authorized.instance_id,
                event_type="ToolCompleted",
                actor_kind="kernel",
                actor_id="kernel",
                correlation_id=authorized.correlation_id,
                redacted_summary=summary[:400],
                task_id=authorized.task_id,
                attempt_id=authorized.attempt_id,
                attributes={
                    "tool": authorized.tool,
                    "receipt_ref": receipt_ref,
                    "duration_ms": duration_ms,
                    "outcome": outcome,
                },
            ),
        )

    stale = await _fence_stale(
        conn,
        org_id=org_id,
        attempt_id=authorized.attempt_id,
        worker_id=authorized.worker_id,
        fencing_token=fencing_token,
    )
    if stale is not None:
        await _tool_completed("discarded", None, f"{authorized.tool} discarded: attempt fenced.")
        return await write_attempt_fenced(
            conn,
            org_id=stale.org_id,
            instance_id=stale.instance_id,
            task_id=stale.task_id,
            attempt_id=authorized.attempt_id,
            correlation_id=stale.correlation_id,
            worker_id=authorized.worker_id,
            proposed_token=stale.proposed_token,
            current_token=stale.current_token,
        )

    if isinstance(invoke, InvokeFailure):
        detail = "Connector call timed out." if invoke.timed_out else invoke.message
        await _tool_completed("failed", None, f"{authorized.tool} failed.")
        return CommittedConnectorFailure(detail=detail, timed_out=invoke.timed_out)

    receipt_ref = await _store_payload(conn, org_id=org_id, body=invoke.content)
    at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    observation = {
        "tool": authorized.tool,
        "at": at,
        "untrusted": True,
        "content": invoke.content,
        "receipt_ref": receipt_ref,
    }
    cur = await conn.execute(
        "select tool_observations from work.attempts where id = %s for update",
        (authorized.attempt_id,),
    )
    row = await cur.fetchone()
    existing = row[0] if row and isinstance(row[0], list) else []
    if not isinstance(existing, list):
        existing = []
    updated = [*existing, observation]
    await conn.execute(
        "update work.attempts set tool_observations = %s where id = %s",
        (Jsonb(updated), authorized.attempt_id),
    )
    await _tool_completed("success", receipt_ref, f"{authorized.tool} completed.")

    budget = authorized.contract.get("budget") or {}
    usage = authorized.usage
    remaining = {
        "tokens": max(0, int(budget.get("tokens") or 0) - int(usage.get("tokens_in") or 0) - int(usage.get("tokens_out") or 0)),
        "cost_usd": max(0.0, float(budget.get("cost_usd") or 0) - float(usage.get("cost_usd") or 0)),
        "time_s": max(0, int(budget.get("time_s") or 0) - int(usage.get("time_s") or 0)),
        "steps": max(0, int(budget.get("steps") or 0) - int(usage.get("steps") or 0)),
        "actions": max(0, int(budget.get("actions") or 0) - int(usage.get("actions") or 0)),
    }

    return {
        "tool": authorized.tool,
        "decision": {"decision_id": authorized.decision_id, "result": "ALLOW"},
        "untrusted": True,
        "content": invoke.content,
        "receipt_ref": receipt_ref,
        "budget_remaining": remaining,
    }


async def call_tool(
    pool,
    *,
    org_id: str,
    attempt_id: str,
    worker_id: str,
    fencing_token: int,
    tool: str,
    args: dict[str, Any],
    broker: CredentialBroker,
    gateway: ToolGateway,
) -> CommittedRefusal | CommittedFenced | CommittedConnectorFailure | dict[str, Any]:
    async with pool.connection() as conn:
        async with conn.transaction():
            auth = await authorize_tool_call(
                conn,
                org_id=org_id,
                attempt_id=attempt_id,
                worker_id=worker_id,
                fencing_token=fencing_token,
                tool=tool,
                args=args,
                broker=broker,
            )
            if isinstance(auth, (CommittedRefusal, CommittedFenced)):
                return auth
            authorized = auth

    invoke = await gateway.invoke_read(
        connector=str(authorized.grant.get("connector") or ""),
        tool=authorized.tool,
        args=authorized.args,
        token=authorized.broker_token,
    )

    async with pool.connection() as conn:
        async with conn.transaction():
            return await complete_tool_call(
                conn,
                org_id=org_id,
                authorized=authorized,
                invoke=invoke,
                fencing_token=fencing_token,
            )
