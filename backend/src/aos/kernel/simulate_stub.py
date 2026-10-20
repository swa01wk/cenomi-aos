"""Stub worker completion for simulation (M2-BE-06)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections.abc import Awaitable, Callable
from typing import Any

from psycopg import AsyncConnection

from . import artifacts, readiness, worker_submit
from .artifacts import parse_artifact_type
from .instances import _load_definitions
from .org import OrgModel
from .simulate_placeholder import placeholder_content
from .worker_fence import FenceMismatch, require_claimed_attempt

SIM_WORKER_ID = "aos-simulate"


async def _claim_admitted(
    conn: AsyncConnection,
    *,
    org_id: str,
    attempt_id: str,
    lease_seconds: float = 90.0,
) -> None:
    lease_until = datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)
    await conn.execute(
        "update work.attempts"
        " set state = 'CLAIMED', worker_id = %s, claimed_at = now(), lease_expires_at = %s"
        " where id = %s and state = 'ADMITTED'",
        (SIM_WORKER_ID, lease_until, attempt_id),
    )


async def _save_skill_produces(
    conn: AsyncConnection,
    *,
    org: OrgModel,
    gate: Any,
    skill_name: str,
    defs: dict[str, dict[str, dict]],
    packs_dir: Path,
) -> list[dict[str, Any]]:
    skill_doc = defs.get("Skill", {}).get(skill_name) or {}
    produces = (skill_doc.get("spec") or {}).get("produces") or []
    refs: list[dict[str, Any]] = []
    for at_name in produces:
        at = parse_artifact_type(defs, str(at_name))
        content = placeholder_content(at)
        saved = await artifacts.save_draft_from_attempt(
            conn,
            org=org,
            gate=gate,
            body={"artifact_type": str(at_name), "content": content, "inputs": [], "sources": []},
            defs=defs,
            packs_dir=packs_dir,
        )
        refs.append(
            {
                "artifact_id": saved["artifact_id"],
                "version": saved["version"],
                "content_hash": saved["content_hash"],
            }
        )
    return refs


def _agent_result_body(gate: Any, *, refs: list[dict[str, Any]], assist: bool) -> dict[str, Any]:
    contract = gate.contract
    body: dict[str, Any] = {
        "schema_version": "aos.agent_result/1",
        "contract_id": contract["contract_id"],
        "attempt_id": gate.attempt_id,
        "status": "completed",
        "output_artifact_refs": refs,
        "evidence_refs": [],
        "input_versions": dict(contract.get("dependency_versions") or {}),
        "consumed_budget": {
            "tokens_in": 0,
            "tokens_out": 0,
            "cost_usd": 0.0,
            "time_s": 0.0,
            "steps": 1,
            "actions": 0,
        },
        "summary": "Completed in simulation.",
    }
    if assist:
        body["reply_blocks"] = [{"kind": "text", "text": "Simulation reply."}]
    return body


async def complete_admitted_attempt(
    conn: AsyncConnection,
    *,
    org: OrgModel,
    org_id: str,
    attempt_id: str,
    packs_dir: Path,
) -> None:
    await _claim_admitted(conn, org_id=org_id, attempt_id=attempt_id)
    cur = await conn.execute(
        "select fencing_token from work.attempts where id = %s",
        (attempt_id,),
    )
    tok_row = await cur.fetchone()
    if tok_row is None:
        return
    gate = await require_claimed_attempt(
        conn,
        org_id=org_id,
        attempt_id=attempt_id,
        worker_id=SIM_WORKER_ID,
        fencing_token=int(tok_row[0]),
    )
    if isinstance(gate, FenceMismatch):
        return
    pack_cur = await conn.execute(
        "select pack_version_id from work.instances where id = %s",
        (gate.instance_id,),
    )
    pvid = str((await pack_cur.fetchone())[0])
    defs = await _load_definitions(conn, pvid)
    tcur = await conn.execute("select skill, kind from work.tasks where id = %s", (gate.task_id,))
    skill_name, kind = await tcur.fetchone()
    refs = await _save_skill_produces(
        conn,
        org=org,
        gate=gate,
        skill_name=str(skill_name),
        defs=defs,
        packs_dir=packs_dir,
    )
    body = _agent_result_body(gate, refs=refs, assist=str(kind) == "assist")
    await worker_submit.submit_result(
        conn,
        org=org,
        org_id=org_id,
        attempt_id=attempt_id,
        worker_id=SIM_WORKER_ID,
        fencing_token=gate.fencing_token,
        result=body,
        packs_dir=packs_dir,
        simulation=True,
    )


async def drain_instance_tasks(
    conn: AsyncConnection,
    *,
    org: OrgModel,
    org_id: str,
    instance_id: str,
    packs_dir: Path,
    after_progress: Callable[[], Awaitable[None]] | None = None,
) -> None:
    """Run readiness and stub-complete every admitted attempt until idle."""
    while True:
        progressed = False
        for task_id in await readiness.candidate_task_ids(conn):
            cur = await conn.execute(
                "select instance_id from work.tasks where id = %s",
                (task_id,),
            )
            row = await cur.fetchone()
            if row is None or str(row[0]) != instance_id:
                continue
            outcome = await readiness.process_ready_task(
                conn, task_id, org=org, packs_dir=packs_dir
            )
            if outcome.outcome == "admitted":
                progressed = True
        acur = await conn.execute(
            "select a.id from work.attempts a"
            " join work.tasks t on t.id = a.task_id"
            " where t.instance_id = %s and a.state = 'ADMITTED'",
            (instance_id,),
        )
        for (attempt_id,) in await acur.fetchall():
            await complete_admitted_attempt(
                conn,
                org=org,
                org_id=org_id,
                attempt_id=str(attempt_id),
                packs_dir=packs_dir,
            )
            if after_progress is not None:
                await after_progress()
            progressed = True
        if not progressed:
            break
