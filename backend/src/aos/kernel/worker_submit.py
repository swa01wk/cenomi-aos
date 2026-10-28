"""submitResult pipeline and idempotent replay (M1-BE-05-B)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .org import OrgModel

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from .contracts import _canonical_json
from .conversation import insert_agent_turn
from .instances import _load_definitions
from .outbox import ExecutionEventWrite, OutboxRow, append_outbox_many, write_execution_event
from . import ids
from .artifacts import parse_artifact_type, validate_artifact_content
from .worker_attempts import (
    WorkerError,
    _instance_participant_audience,
    emit_task_state_changed,
    end_claimed_attempt,
    merge_usage,
    seat_display_name,
)
from .worker_fence import ClaimedAttempt, CommittedFenced, require_claimed_attempt


def agent_result_request_hash(body: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(body)).hexdigest()


async def check_submit_idempotency(
    conn: AsyncConnection,
    *,
    org_id: str,
    attempt_id: str,
    worker_id: str,
    request_hash: str,
) -> dict[str, Any] | None:
    cur = await conn.execute(
        "select a.state, a.outcome, a.worker_id, a.submit_response, a.submit_request_hash"
        " from work.attempts a"
        " join work.tasks t on t.id = a.task_id"
        " join work.instances i on i.id = t.instance_id"
        " where a.id = %s and i.org_id = %s"
        " for update of a",
        (attempt_id, org_id),
    )
    row = await cur.fetchone()
    if row is None:
        raise WorkerError("not_found", 404, "Attempt not found", f"No attempt {attempt_id!r}.")
    state, outcome, row_worker, submit_response, stored_hash = row
    if state != "ENDED" or outcome != "submitted":
        return None
    if row_worker != worker_id:
        return None
    if submit_response is None:
        return None
    response = submit_response if isinstance(submit_response, dict) else json.loads(submit_response)
    if stored_hash == request_hash:
        return response
    raise WorkerError(
        "conflict",
        409,
        "Submit body differs",
        "This attempt already ended with a different result.",
    )


async def load_current_dependency_versions(
    conn: AsyncConnection,
    instance_id: str,
    contract: dict[str, Any],
) -> dict[str, int]:
    cur = await conn.execute("select attributes from work.instances where id = %s", (instance_id,))
    row = await cur.fetchone()
    attrs = row[0] if row else {}
    if not isinstance(attrs, dict):
        attrs = json.loads(attrs or "{}")
    deps = contract.get("dependency_versions") or {}
    out: dict[str, int] = {}
    for key in deps:
        val = attrs.get(key)
        if isinstance(val, int):
            out[key] = val
        elif val is not None:
            out[key] = int(val)
    return out


async def _store_output_verification(
    conn: AsyncConnection,
    *,
    refs: list[dict[str, Any]],
    verification: dict[str, Any],
) -> None:
    for ref in refs:
        aid = ref.get("artifact_id")
        version = ref.get("version")
        if not aid or version is None:
            continue
        await conn.execute(
            "update work.artifact_versions set verification = %s"
            " where artifact_id = %s and version = %s",
            (Jsonb(verification), str(aid), int(version)),
        )


async def _emit_verification_completed(
    conn: AsyncConnection,
    *,
    gate: ClaimedAttempt,
    verifier_name: str,
    verdict: str,
    findings: list[str],
) -> None:
    on_behalf = gate.contract.get("on_behalf_of") or {}
    role = on_behalf.get("role")
    if not role:
        return
    payload: dict[str, Any] = {
        "instance_id": gate.instance_id,
        "task_id": gate.task_id,
        "verifier": verifier_name,
        "verdict": verdict,
    }
    if findings:
        payload["findings"] = findings
    await append_outbox_many(
        conn,
        [
            OutboxRow(
                stream=ids.stream_instance(gate.instance_id),
                event_type="verification.completed",
                instance_id=gate.instance_id,
                audience={"roles": [str(role)]},
                data=payload,
            )
        ],
    )


async def _validate_outputs(
    conn: AsyncConnection,
    *,
    gate: ClaimedAttempt,
    refs: list[dict[str, Any]],
    defs: dict[str, dict[str, dict]],
) -> None:
    for ref in refs:
        aid = ref.get("artifact_id")
        version = ref.get("version")
        expected_hash = ref.get("content_hash")
        if not aid or version is None or not expected_hash:
            raise WorkerError("validation_failed", 422, "Invalid output ref", "Each output needs artifact_id, version, content_hash.")
        cur = await conn.execute(
            "select v.content_hash, v.produced_by, v.content, a.artifact_type, a.instance_id"
            " from work.artifact_versions v"
            " join work.artifacts a on a.id = v.artifact_id"
            " where v.artifact_id = %s and v.version = %s",
            (aid, int(version)),
        )
        row = await cur.fetchone()
        if row is None:
            raise WorkerError("validation_failed", 422, "Output not found", f"No version {version} for {aid!r}.")
        stored_hash, producer, content, artifact_type, inst_id = row
        if inst_id != gate.instance_id:
            raise WorkerError("validation_failed", 422, "Output not on this job", f"Artifact {aid!r} belongs elsewhere.")
        if producer != gate.attempt_id:
            raise WorkerError(
                "validation_failed",
                422,
                "Output not from this attempt",
                f"Version {version} of {aid!r} was not produced by this attempt.",
            )
        if stored_hash != expected_hash:
            raise WorkerError("validation_failed", 422, "Content hash mismatch", "Reload the draft and submit again.")
        content_doc = content if isinstance(content, dict) else json.loads(content)
        at = parse_artifact_type(defs, artifact_type)
        errors = validate_artifact_content(at.spec, content_doc, partial=False)
        if errors:
            raise WorkerError(
                "validation_failed",
                422,
                "Output content invalid",
                "Fix the draft before submitting.",
                errors=errors,
            )


async def _record_verification(
    conn: AsyncConnection,
    *,
    gate: ClaimedAttempt,
    refs: list[dict[str, Any]],
    verifier_doc: dict[str, Any],
) -> None:
    """Stamp the verdict on each output version and tell the reviewing role (and the Console)."""
    verification = {
        "verifier": verifier_doc["name"],
        "verdict": verifier_doc["verdict"],
        "findings": list(verifier_doc["findings"]),
    }
    for ref in refs:
        await conn.execute(
            "update work.artifact_versions set verification = %s where artifact_id = %s and version = %s",
            (Jsonb(verification), ref["artifact_id"], int(ref["version"])),
        )
    role = (gate.contract.get("on_behalf_of") or {}).get("role")
    await append_outbox_many(
        conn,
        [
            OutboxRow(
                stream=ids.stream_instance(gate.instance_id),
                event_type="verification.completed",
                instance_id=gate.instance_id,
                audience={"roles": [str(role)]} if role else {},
                data={"instance_id": gate.instance_id, "task_id": gate.task_id, **verification},
            )
        ],
    )


async def _finish_submit(
    conn: AsyncConnection,
    *,
    gate: ClaimedAttempt,
    worker_id: str,
    fencing_token: int,
    result: dict[str, Any],
    response: dict[str, Any],
    request_hash: str,
    task_to_state: str,
    reply_blocks: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    merged = merge_usage(gate.usage, result.get("consumed_budget") or {})
    await conn.execute(
        "update work.attempts set usage = %s where id = %s",
        (Jsonb(merged), gate.attempt_id),
    )
    from_state = gate.task_state
    end = await end_claimed_attempt(
        conn,
        org_id=gate.org_id,
        attempt_id=gate.attempt_id,
        worker_id=worker_id,
        fencing_token=fencing_token,
        outcome="submitted",
        reserve_if_empty=False,
    )
    if not end.ended:
        if end.fenced:
            return end.fenced  # type: ignore[return-value]
        raise WorkerError("conflict", 409, "Attempt already ended", "Submit could not finish.")

    await conn.execute(
        "update work.attempts set submit_response = %s, submit_request_hash = %s where id = %s",
        (Jsonb(response), request_hash, gate.attempt_id),
    )
    await conn.execute(
        "update work.tasks set state = %s, updated_at = now() where id = %s",
        (task_to_state, gate.task_id),
    )
    if from_state != task_to_state:
        await emit_task_state_changed(
            conn,
            instance_id=gate.instance_id,
            task_id=gate.task_id,
            template=gate.contract.get("template", "assist"),
            from_state=from_state,
            to_state=task_to_state,
        )

    audience = await _instance_participant_audience(conn, gate.instance_id)
    author_name = await seat_display_name(
        conn, org_id=gate.org_id, seat_name=gate.seat, seat_version=gate.seat_version
    )
    if reply_blocks and gate.kind == "assist":
        turn = await insert_agent_turn(
            conn,
            instance_id=gate.instance_id,
            seat_id=gate.seat,
            seat_name=author_name,
            blocks=reply_blocks,
            audience_roles=audience.get("roles"),
            attempt_id=gate.attempt_id,
        )
        turn_payload = {
            "turn_id": turn["turn_id"],
            "seq": turn["seq"],
            "author": turn["author"],
            "blocks": turn["blocks"],
            "at": turn["at"],
            "attempt_id": gate.attempt_id,
        }
        await append_outbox_many(
            conn,
            [
                OutboxRow(
                    stream=ids.stream_instance(gate.instance_id),
                    event_type="agent.message.completed",
                    instance_id=gate.instance_id,
                    audience=audience,
                    data={"instance_id": gate.instance_id, "turn": turn_payload},
                )
            ],
        )
    return response


async def submit_result(
    conn: AsyncConnection,
    *,
    org: "OrgModel",
    org_id: str,
    attempt_id: str,
    worker_id: str,
    fencing_token: int,
    result: dict[str, Any],
    packs_dir: Path,
    simulation: bool = False,
) -> dict[str, Any] | CommittedFenced:
    request_hash = agent_result_request_hash(result)
    replay = await check_submit_idempotency(
        conn, org_id=org_id, attempt_id=attempt_id, worker_id=worker_id, request_hash=request_hash
    )
    if replay is not None:
        return replay

    gate = await require_claimed_attempt(
        conn, org_id=org_id, attempt_id=attempt_id, worker_id=worker_id, fencing_token=fencing_token
    )
    if isinstance(gate, CommittedFenced):
        return gate
    if simulation and "-SIM-" not in str(gate.instance_id):
        # Skipping the verifier is for aos simulate's rolled-back jobs only, never a real job.
        raise WorkerError("internal", 500, "Simulation flag on a real job", "Verifiers can't be skipped here.")

    if result.get("attempt_id") != attempt_id:
        raise WorkerError("validation_failed", 422, "Wrong attempt", "attempt_id does not match the URL.")
    if result.get("contract_id") != gate.contract.get("contract_id"):
        raise WorkerError("validation_failed", 422, "Wrong contract", "contract_id does not match this attempt.")

    status = result.get("status")
    if status == "needs_input":
        raise WorkerError(
            "validation_failed",
            422,
            "Use askQuestions",
            "needs_input must be sent through askQuestions, not submitResult.",
        )

    pack_version_id = None
    icur = await conn.execute(
        "select pack_version_id from work.instances where id = %s",
        (gate.instance_id,),
    )
    irow = await icur.fetchone()
    if irow:
        pack_version_id = str(irow[0])
    defs = await _load_definitions(conn, pack_version_id) if pack_version_id else {}

    refs = result.get("output_artifact_refs") or []
    await _validate_outputs(conn, gate=gate, refs=refs, defs=defs)

    current_deps = await load_current_dependency_versions(conn, gate.instance_id, gate.contract)
    input_versions = result.get("input_versions") or {}
    if input_versions != current_deps:
        stale_response = {
            "verdict": "STALE",
            "task_state": "READY",
            "verifier": None,
            "next_attempt": True,
        }
        await write_execution_event(
            conn,
            ExecutionEventWrite(
                org_id=gate.org_id,
                run_id=gate.instance_id,
                event_type="TaskResultProposed",
                actor_kind="seat",
                actor_id=gate.seat,
                correlation_id=gate.correlation_id,
                redacted_summary=result.get("summary", "")[:400],
                task_id=gate.task_id,
                attempt_id=attempt_id,
                attributes={"status": status, "output_artifact_refs": len(refs)},
            ),
        )
        await write_execution_event(
            conn,
            ExecutionEventWrite(
                org_id=gate.org_id,
                run_id=gate.instance_id,
                event_type="TaskRejected",
                actor_kind="kernel",
                actor_id="kernel",
                correlation_id=gate.correlation_id,
                redacted_summary="Inputs changed since the attempt started.",
                task_id=gate.task_id,
                attempt_id=attempt_id,
                attributes={"stage": "freshness", "verdict": "STALE"},
            ),
        )
        finished = await _finish_submit(
            conn,
            gate=gate,
            worker_id=worker_id,
            fencing_token=fencing_token,
            result=result,
            response=stale_response,
            request_hash=request_hash,
            task_to_state="READY",
            reply_blocks=None,
        )
        if isinstance(finished, CommittedFenced):
            return finished
        return stale_response

    if status == "failed":
        raise WorkerError("validation_failed", 422, "Use failAttempt", "failed results must use failAttempt.")

    reply_blocks = result.get("reply_blocks")
    if gate.kind == "assist" and not reply_blocks:
        raise WorkerError(
            "validation_failed",
            422,
            "Reply blocks required",
            "Assist attempts must include reply_blocks when status is completed.",
        )

    tcur = await conn.execute("select verifier from work.tasks where id = %s", (gate.task_id,))
    verifier_name = (await tcur.fetchone() or (None,))[0]

    accepted_response = {
        "verdict": "ACCEPTED",
        "task_state": "WAITING_INPUT" if gate.kind == "assist" else "VERIFYING",
        "verifier": None,
        "next_attempt": False,
    }
    task_to = "WAITING_INPUT" if gate.kind == "assist" else "VERIFYING"
    verifier_doc: dict[str, Any] | None = None

    if verifier_name and gate.kind != "assist" and not simulation:
        from . import verify

        verdict, findings = await verify.run_task_verifier(
            conn,
            verifier_name=str(verifier_name),
            defs=defs,
            gate=gate,
            result=result,
        )
        verifier_doc = {"name": str(verifier_name), "verdict": verdict, "findings": findings}
        accepted_response["verifier"] = verifier_doc
        stored_verification = {
            "verifier": str(verifier_name),
            "verdict": verdict,
            "findings": findings,
        }
        await _store_output_verification(conn, refs=refs, verification=stored_verification)
        await _emit_verification_completed(
            conn,
            gate=gate,
            verifier_name=str(verifier_name),
            verdict=verdict,
            findings=findings,
        )
        if verdict == "REWORK":
            accepted_response["verdict"] = "REWORK"
            if gate.attempts_used >= gate.max_attempts:
                accepted_response["task_state"] = "EXCEPTION"
                accepted_response["next_attempt"] = False
                task_to = "EXCEPTION"
            else:
                accepted_response["task_state"] = "READY"
                accepted_response["next_attempt"] = True
                task_to = "READY"
            await write_execution_event(
                conn,
                ExecutionEventWrite(
                    org_id=gate.org_id,
                    run_id=gate.instance_id,
                    event_type="TaskRejected",
                    actor_kind="kernel",
                    actor_id="kernel",
                    correlation_id=gate.correlation_id,
                    redacted_summary="Verifier asked for rework.",
                    task_id=gate.task_id,
                    attempt_id=attempt_id,
                    attributes={"stage": "verify", "verdict": "REWORK"},
                ),
            )
        elif verdict == "FAIL":
            accepted_response["verdict"] = "FAILED"
            accepted_response["task_state"] = "EXCEPTION"
            task_to = "EXCEPTION"
            await write_execution_event(
                conn,
                ExecutionEventWrite(
                    org_id=gate.org_id,
                    run_id=gate.instance_id,
                    event_type="TaskRejected",
                    actor_kind="kernel",
                    actor_id="kernel",
                    correlation_id=gate.correlation_id,
                    redacted_summary="Verifier failed the output.",
                    task_id=gate.task_id,
                    attempt_id=attempt_id,
                    attributes={"stage": "verify", "verdict": "FAIL"},
                ),
            )
        else:
            task_to = "COMPLETED"
            accepted_response["task_state"] = "COMPLETED"
    elif gate.kind != "assist":
        task_to = "COMPLETED"
        accepted_response["task_state"] = "COMPLETED"
    await write_execution_event(
        conn,
        ExecutionEventWrite(
            org_id=gate.org_id,
            run_id=gate.instance_id,
            event_type="TaskResultProposed",
            actor_kind="seat",
            actor_id=gate.seat,
            correlation_id=gate.correlation_id,
            redacted_summary=result.get("summary", "")[:400],
            task_id=gate.task_id,
            attempt_id=attempt_id,
            attributes={"status": status, "output_artifact_refs": len(refs)},
        ),
    )
    if accepted_response["verdict"] == "ACCEPTED":
        await write_execution_event(
            conn,
            ExecutionEventWrite(
                org_id=gate.org_id,
                run_id=gate.instance_id,
                event_type="TaskAccepted",
                actor_kind="kernel",
                actor_id="kernel",
                correlation_id=gate.correlation_id,
                redacted_summary="Submit checks passed.",
                task_id=gate.task_id,
                attempt_id=attempt_id,
                attributes={"verdict": "PASS"},
            ),
        )
    finished = await _finish_submit(
        conn,
        gate=gate,
        worker_id=worker_id,
        fencing_token=fencing_token,
        result=result,
        response=accepted_response,
        request_hash=request_hash,
        task_to_state=task_to,
        reply_blocks=reply_blocks if isinstance(reply_blocks, list) else None,
    )
    if isinstance(finished, CommittedFenced):
        return finished
    if verifier_doc is not None:
        await _record_verification(conn, gate=gate, refs=refs, verifier_doc=verifier_doc)
    if gate.kind != "assist" and task_to == "COMPLETED":
        from . import events as workflow_events

        await workflow_events.on_workflow_task_completed(
            conn,
            org,
            instance_id=gate.instance_id,
            task_id=gate.task_id,
            packs_dir=packs_dir,
        )
    if gate.kind != "assist" and task_to in ("COMPLETED", "READY", "EXCEPTION"):
        summary = result.get("summary") if isinstance(result.get("summary"), str) else None
        if task_to == "EXCEPTION":
            from .task_retry import finalize_workflow_task_exception

            await finalize_workflow_task_exception(
                conn,
                org=org,
                org_id=gate.org_id,
                instance_id=gate.instance_id,
                task_id=gate.task_id,
                attempt_id=attempt_id,
                summary=summary,
            )
        else:
            from .progress import post_task_outcome_progress

            await post_task_outcome_progress(
                conn,
                org=org,
                org_id=gate.org_id,
                instance_id=gate.instance_id,
                task_id=gate.task_id,
                summary=summary,
                attempt_id=attempt_id,
            )
    return accepted_response
