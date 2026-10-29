"""Jobs (instances), snapshot projection and workspace commands (M1-BE-04 A)."""

from __future__ import annotations

import json
import secrets
from pathlib import Path
from typing import Any

from psycopg import AsyncConnection, errors as pg_errors
from psycopg.types.json import Jsonb

from aos.registry.kinds import TaskTemplate, WorkflowDefinition

from . import artifacts, contracts, decisions, ids
from . import workflow as workflow_ops
from .admission import (
    AdmissionContext,
    check_admission,
    count_live_seat_attempts,
    refuse_budget_exhausted,
    refuse_live_attempt_conflict,
    task_has_live_attempt,
)
from .console import _waiting_on
from .contracts import PackMaterialError, finalize_assist_contract, resolve_assist_skill
from .conversation import (
    find_turn_by_client_id,
    insert_person_turn,
    project_turn,
    turn_visible,
)
from .org import OrgModel
from .outbox import ExecutionEventWrite, OutboxRow, append_outbox_many, write_execution_event
from .refusal import CommittedRefusal
from .intake_routing import route_intake_message
from .job_title import derive_job_title
from .request_detail import message_indicates_request_detail
from .seats import may_start_workflow, seat_audience
from . import tasks as task_ops


def _seat_colleague(seat_doc: dict[str, Any] | None, db_display_name: str) -> dict[str, Any]:
    if seat_doc is None:
        return {"colleague_name": db_display_name, "title": ""}
    spec = seat_doc.get("spec") or {}
    persona = spec.get("persona")
    title = str(spec.get("display_name") or "").strip()
    colleague_name = db_display_name
    if isinstance(persona, dict):
        gn = str(persona.get("given_name") or "").strip()
        fn = str(persona.get("family_name") or "").strip()
        title = str(persona.get("title") or title).strip()
        full = f"{gn} {fn}".strip()
        if full:
            colleague_name = full
    out: dict[str, Any] = {"colleague_name": colleague_name, "title": title}
    if isinstance(persona, dict) and persona:
        out["persona"] = {
            "given_name": str(persona.get("given_name") or ""),
            "family_name": str(persona.get("family_name") or ""),
            "title": title,
        }
    return out


class InstanceError(Exception):
    def __init__(self, code: str, status: int, title: str, detail: str = "", **extra: Any) -> None:
        self.code = code
        self.status = status
        self.title = title
        self.detail = detail
        self.extra = extra
        super().__init__(title)


def _intake_view_artifact_type(wdoc: dict[str, Any]) -> str | None:
    """Artifact type name for the workflow's initial state view (from pack workflow data)."""
    spec = wdoc.get("spec") or {}
    initial = spec.get("initial")
    if not initial:
        return None
    state = (spec.get("states") or {}).get(initial) or {}
    view = state.get("view")
    return str(view) if view else None


async def _assert_repeat_source(
    conn: AsyncConnection,
    *,
    org_id: str,
    actor: str,
    starter_role: str,
    workflow_name: str,
    repeat_from_instance_id: str,
) -> None:
    cur = await conn.execute(
        "select status, workflow, org_id from work.instances where id = %s",
        (repeat_from_instance_id,),
    )
    row = await cur.fetchone()
    if row is None:
        raise InstanceError(
            "not_found",
            404,
            "Prior job not found",
            f"No job {repeat_from_instance_id!r}.",
        )
    status, src_workflow, src_org = str(row[0]), str(row[1]), str(row[2])
    if src_org != org_id:
        raise InstanceError("not_found", 404, "Prior job not found", "That job is not in your organization.")
    if status != "closed":
        raise InstanceError(
            "conflict",
            409,
            "Prior job not finished",
            "Repeat order only works from a completed job.",
        )
    if src_workflow != workflow_name:
        raise InstanceError(
            "validation_failed",
            422,
            "Different workflow",
            "The prior job must use the same workflow as this one.",
        )
    pcur = await conn.execute(
        "select 1 from work.participants where instance_id = %s and person_id = %s and role = %s",
        (repeat_from_instance_id, actor, starter_role),
    )
    if await pcur.fetchone() is None:
        raise InstanceError(
            "not_permitted",
            403,
            "Not your prior job",
            "You can only repeat a job you started as the requester.",
        )


async def _load_definitions(conn: AsyncConnection, pack_version_id: str) -> dict[str, dict[str, dict]]:
    cur = await conn.execute(
        "select kind, name, spec from registry.definitions where pack_version_id = %s",
        (pack_version_id,),
    )
    by_kind: dict[str, dict[str, dict]] = {}
    for kind, name, spec in await cur.fetchall():
        doc = spec if isinstance(spec, dict) else json.loads(spec)
        by_kind.setdefault(kind, {})[name] = doc
    return by_kind


def _state_tasks(wdoc: dict[str, Any], state: str) -> list[TaskTemplate]:
    st = WorkflowDefinition.model_validate(wdoc).spec.states.get(state)
    return list(st.tasks) if st else []


async def _pack_meta(conn: AsyncConnection, org_id: str, pack_version_id: str) -> tuple[str, int, str, str]:
    cur = await conn.execute(
        "select pack_name, version, digest, status from registry.pack_versions where id = %s and org_id = %s",
        (pack_version_id, org_id),
    )
    row = await cur.fetchone()
    if row is None:
        raise InstanceError("not_found", 404, "Pack version not found", "No such pinned pack version.")
    return row[0], int(row[1]), row[2], row[3]


async def _idempotent_instance_id(
    conn: AsyncConnection, org_id: str, actor: str, idempotency_key: str | None
) -> str | None:
    if not idempotency_key:
        return None
    cur = await conn.execute(
        "select id from work.instances where org_id = %s and created_by = %s and idempotency_key = %s",
        (org_id, actor, idempotency_key),
    )
    row = await cur.fetchone()
    return row[0] if row else None


async def _lock_seat_for_admission(
    conn: AsyncConnection, org_id: str, seat_name: str
) -> tuple | None:
    cur = await conn.execute(
        "select name, version, pack_version_id, display_name, placement, owner_person_id, state"
        " from registry.seats"
        " where org_id = %s and name = %s"
        " order by (case when state = 'ACTIVE' then 0 else 1 end), version desc"
        " limit 1"
        " for update",
        (org_id, seat_name),
    )
    return await cur.fetchone()


def _pack_material_error(exc: PackMaterialError) -> InstanceError:
    return InstanceError(exc.code, exc.status, exc.title, exc.detail)


def _is_budget_ledger_violation(exc: BaseException) -> bool:
    return isinstance(exc, pg_errors.CheckViolation) and exc.diag.table_name == "budget_ledger"


def _is_one_live_violation(exc: BaseException) -> bool:
    return isinstance(exc, pg_errors.UniqueViolation) and exc.diag.constraint_name == "attempts_one_live"


def _is_instance_idempotency_violation(exc: BaseException) -> bool:
    return (
        isinstance(exc, pg_errors.UniqueViolation)
        and exc.diag.constraint_name == "instances_org_id_created_by_idempotency_key_key"
    )


async def _refusal_from_admit_backstop(
    conn: AsyncConnection, ctx: AdmissionContext, exc: BaseException
) -> CommittedRefusal | None:
    if _is_budget_ledger_violation(exc):
        return await refuse_budget_exhausted(conn, ctx)
    if _is_one_live_violation(exc):
        return await refuse_live_attempt_conflict(conn, ctx)
    return None


def _seat_limits(seat_doc: dict) -> dict[str, Any]:
    limits = (seat_doc.get("spec") or {}).get("limits") or {}
    required = (
        "daily_cost_usd",
        "attempt_cost_usd",
        "attempt_tokens",
        "attempt_steps",
        "attempt_actions",
        "run_minutes",
    )
    missing = [k for k in required if k not in limits]
    if missing:
        raise InstanceError(
            "internal",
            500,
            "Seat limits incomplete",
            f"Seat limits missing: {', '.join(missing)}",
        )
    return limits


def _initial_task_template(workflow_doc: dict) -> dict[str, Any]:
    spec = workflow_doc.get("spec") or {}
    initial = spec.get("initial")
    states = spec.get("states") or {}
    state = states.get(initial) or {}
    templates = state.get("tasks") or []
    if not templates:
        raise InstanceError(
            "conflict",
            409,
            "Workflow cannot start",
            f"Initial state {initial!r} has no task templates.",
        )
    return templates[0]


def _state_order(spec: dict) -> list[str]:
    """Workflow states in flow order.

    Definitions are stored as jsonb, which doesn't keep object key order, so ``spec.states`` can't give the order.
    Walk the transitions (a list, so its order is kept) breadth-first from ``initial``; states no transition
    reaches follow in name order.
    """
    states = spec.get("states") or {}
    initial = spec.get("initial")
    order: list[str] = []
    if initial in states:
        order.append(initial)
    transitions = [t for t in (spec.get("transitions") or []) if isinstance(t, dict)]
    i = 0
    while i < len(order):
        for t in transitions:
            froms = t.get("from")
            froms = froms if isinstance(froms, list) else [froms]
            to = t.get("to")
            if order[i] in froms and to in states and to not in order:
                order.append(to)
        i += 1
    order.extend(sorted(n for n in states if n not in order))
    return order


def _stages(workflow_doc: dict, current_state: str) -> list[dict[str, str]]:
    spec = workflow_doc.get("spec") or {}
    states = spec.get("states") or {}
    names = _state_order(spec)
    if current_state not in states:
        current_state = names[0] if names else current_state
    idx = names.index(current_state) if current_state in names else 0
    out: list[dict[str, str]] = []
    for i, name in enumerate(names):
        label = (states[name].get("label") or name) if isinstance(states[name], dict) else name
        if i < idx:
            status = "done"
        elif i == idx:
            status = "current"
        else:
            status = "next"
        out.append({"state": name, "label": label, "status": status})
    return out


async def _stream_cursor(conn: AsyncConnection, instance_id: str) -> str:
    stream = ids.stream_instance(instance_id)
    cur = await conn.execute("select last_seq from evidence.stream_heads where stream = %s", (stream,))
    row = await cur.fetchone()
    seq = int(row[0]) if row else 0
    return ids.ui_event_cursor(stream, seq)


async def list_digital_workers(
    conn: AsyncConnection, org: OrgModel, org_id: str, person_id: str, roles: list[str]
) -> list[dict[str, Any]]:
    cur = await conn.execute(
        "select name, version, display_name, state, pack_version_id, owner_person_id, placement"
        " from registry.seats where org_id = %s and state = 'ACTIVE'",
        (org_id,),
    )
    items: list[dict[str, Any]] = []
    role_set = set(roles)
    for name, version, display_name, state, pvid, owner, placement in await cur.fetchall():
        defs = await _load_definitions(conn, str(pvid))
        wf_docs = list(defs.get("WorkflowDefinition", {}).values())
        if person_id not in seat_audience(
            org, owner_person_id=owner, placement=placement, workflow_docs=wf_docs
        ):
            continue
        workflows: list[dict[str, str]] = []
        seat_doc = defs.get("Seat", {}).get(name)
        colleague = _seat_colleague(seat_doc, display_name)
        seat_role = str((seat_doc or {}).get("spec", {}).get("role") or "")
        for wname, wdoc in defs.get("WorkflowDefinition", {}).items():
            spec = wdoc.get("spec") or {}
            if seat_role and str(spec.get("seat_role") or "") != seat_role:
                continue
            if may_start_workflow(wdoc, role_set) is None:
                continue
            hints = spec.get("intake_hints") or []
            workflows.append(
                {
                    "name": wname,
                    "title": spec.get("title", wname),
                    "description": spec.get("description", ""),
                    "intake_hints": hints if isinstance(hints, list) else [],
                }
            )
        if not workflows:
            continue
        items.append(
            {
                "seat": name,
                "display_name": display_name,
                "colleague_name": colleague["colleague_name"],
                "title": colleague["title"],
                "persona": colleague.get("persona"),
                "version": version,
                "state": state,
                "workflows": workflows,
            }
        )
    return items


async def list_my_instances(
    conn: AsyncConnection,
    org: OrgModel,
    org_id: str,
    person_id: str,
    *,
    status: str | None,
) -> list[dict[str, Any]]:
    cur = await conn.execute(
        "select i.id, i.title, i.workflow, i.state, i.version, i.seat, i.created_at, i.closed_at, i.status,"
        " i.state_entered_at"
        " from work.instances i"
        " join work.participants p on p.instance_id = i.id"
        " where i.org_id = %s and p.person_id = %s"
        " order by i.created_at desc",
        (org_id, person_id),
    )
    rows = await cur.fetchall()
    items: list[dict[str, Any]] = []
    for row in rows:
        inst_id, title, workflow, state, version, seat, created_at, closed_at, inst_status, state_entered_at = row
        if status == "closed" and inst_status not in ("closed", "cancelled"):
            continue
        if status == "active" and inst_status != "running":
            continue
        waiting = await _waiting_on(conn, org, inst_id)
        if status == "waiting_on_me":
            if waiting.get("kind") != "person" or waiting.get("person_id") != person_id:
                continue
        state_label = state
        items.append(
            {
                "instance_id": inst_id,
                "title": title,
                "workflow": workflow,
                "seat": seat,
                "state": state,
                "state_label": state_label,
                "version": version,
                "waiting_on": waiting,
                "started_at": created_at.isoformat(),
                "closed_at": closed_at.isoformat() if closed_at else None,
                "last_activity_at": state_entered_at.isoformat(),
            }
        )
    return items


async def _participant_roles(conn: AsyncConnection, instance_id: str, person_id: str) -> list[str]:
    cur = await conn.execute(
        "select role from work.participants where instance_id = %s and person_id = %s",
        (instance_id, person_id),
    )
    return [r[0] for r in await cur.fetchall()]


async def _fetch_turns(
    conn: AsyncConnection,
    org: OrgModel,
    instance_id: str,
    viewer_roles: list[str],
    *,
    limit: int = 50,
    before_seq: int | None = None,
) -> list[dict[str, Any]]:
    if before_seq is not None:
        cur = await conn.execute(
            "select id, seq, author_kind, author_id, audience_roles, blocks, attempt_id, at"
            " from work.turns where instance_id = %s and seq < %s order by seq desc limit %s",
            (instance_id, before_seq, limit),
        )
    else:
        cur = await conn.execute(
            "select id, seq, author_kind, author_id, audience_roles, blocks, attempt_id, at"
            " from work.turns where instance_id = %s order by seq desc limit %s",
            (instance_id, limit),
        )
    rows = await cur.fetchall()
    # Agent turns name the Seat by its display name, as the live turn event does.
    seat_cur = await conn.execute(
        "select i.seat, s.display_name from work.instances i"
        " join registry.seats s on s.org_id = i.org_id and s.name = i.seat and s.version = i.seat_version"
        " where i.id = %s",
        (instance_id,),
    )
    seat_row = await seat_cur.fetchone()
    seat_names = {seat_row[0]: seat_row[1]} if seat_row else {}
    out: list[dict[str, Any]] = []
    for row in reversed(rows):
        if not turn_visible(row[4], viewer_roles):
            continue
        if row[2] == "person":
            pname = org.people[row[3]].name if row[3] in org.people else row[3]
        else:
            pname = seat_names.get(row[3], row[3])
        out.append(project_turn(row, person_name=pname))
    return out


async def refresh_decisions_for_viewer(
    conn: AsyncConnection,
    org: OrgModel,
    instance_id: str,
    *,
    packs_dir: Path,
) -> None:
    """Reconcile join regions and open decisions when the client loads a snapshot."""
    from . import decisions as decision_ops

    await decision_ops.open_ready_decisions(conn, instance_id, org=org, packs_dir=packs_dir)


async def build_snapshot(
    conn: AsyncConnection,
    org: OrgModel,
    org_id: str,
    instance_id: str,
    person_id: str,
) -> dict[str, Any]:
    cur = await conn.execute(
        "select id, title, workflow, pack_version_id, state, version, seat, seat_version"
        " from work.instances where id = %s and org_id = %s",
        (instance_id, org_id),
    )
    row = await cur.fetchone()
    if row is None:
        raise InstanceError("not_found", 404, "Job not found", f"No instance {instance_id!r}.")
    _, title, workflow, pvid, state, version, seat, seat_version = row
    my_roles = await _participant_roles(conn, instance_id, person_id)
    if not my_roles:
        raise InstanceError("not_permitted", 403, "Not a participant", "You are not part of this job.")
    pack_name, pack_ver, digest, _ = await _pack_meta(conn, org_id, str(pvid))
    defs = await _load_definitions(conn, str(pvid))
    wdoc = defs.get("WorkflowDefinition", {}).get(workflow)
    if wdoc is None:
        raise InstanceError("internal", 500, "Workflow missing", f"Workflow {workflow!r} not on pinned pack.")
    parts_cur = await conn.execute(
        "select role, person_id, bound_by from work.participants where instance_id = %s order by role",
        (instance_id,),
    )
    participants = []
    for role, pid, bound_by in await parts_cur.fetchall():
        participants.append(
            {
                "role": role,
                "person_id": pid,
                "name": org.people[pid].name if pid in org.people else pid,
                "bound_by": bound_by,
            }
        )
    seat_doc = defs.get("Seat", {}).get(seat)
    seat_cur = await conn.execute(
        "select display_name from registry.seats where org_id = %s and name = %s and version = %s",
        (org_id, seat, seat_version),
    )
    seat_disp_row = await seat_cur.fetchone()
    db_display = str(seat_disp_row[0]) if seat_disp_row else seat
    colleague = _seat_colleague(seat_doc, db_display)
    turns = await _fetch_turns(conn, org, instance_id, my_roles, limit=50)
    cursor = await _stream_cursor(conn, instance_id)
    return {
        "instance_id": instance_id,
        "title": title,
        "workflow": workflow,
        "seat": seat,
        "assignee": {
            "seat": seat,
            "colleague_name": colleague["colleague_name"],
            "title": colleague["title"],
            **({"persona": colleague["persona"]} if colleague.get("persona") else {}),
        },
        "pack_version": f"{pack_name}@{pack_ver}",
        "state": state,
        "version": version,
        "stages": _stages(wdoc, state),
        "participants": participants,
        "my_roles": my_roles,
        "pending": await decisions.pending_for_viewer(conn, instance_id, person_id, my_roles),
        "artifacts": await artifacts.summaries_for_instance(
            conn, org, instance_id, my_roles, defs
        ),
        "turns": turns,
        "cursor": cursor,
    }


async def start_instance(
    conn: AsyncConnection,
    org: OrgModel,
    *,
    org_id: str,
    actor: str,
    roles: list[str],
    seat_name: str,
    workflow_name: str,
    first_message: str,
    idempotency_key: str | None,
    packs_dir: Path,
    simulation_instance_id: str | None = None,
    repeat_from_instance_id: str | None = None,
) -> dict[str, Any] | CommittedRefusal:
    existing_id = await _idempotent_instance_id(conn, org_id, actor, idempotency_key)
    if existing_id:
        return await build_snapshot(conn, org, org_id, existing_id, actor)

    seat_row = await _lock_seat_for_admission(conn, org_id, seat_name)
    if seat_row is None:
        raise InstanceError("not_found", 404, "Seat not found", f"No seat {seat_name!r}.")

    (
        _sname,
        seat_version,
        pack_version_id,
        _display,
        _placement,
        _owner,
        seat_state,
    ) = seat_row
    pack_name, pack_ver, pack_digest, pack_status = await _pack_meta(conn, org_id, str(pack_version_id))
    defs = await _load_definitions(conn, str(pack_version_id))
    wdoc = defs.get("WorkflowDefinition", {}).get(workflow_name)
    if wdoc is None:
        raise InstanceError(
            "not_found",
            404,
            "Workflow not found",
            f"No workflow {workflow_name!r} on this seat.",
        )
    seat_doc = defs.get("Seat", {}).get(seat_name)
    limits_doc = seat_doc or {}
    limits = _seat_limits(limits_doc) if seat_doc else {}
    reservation = float(limits.get("attempt_cost_usd", 0.0))
    budget = contracts.seat_budget_block(limits) if limits else {"retries": 2}
    max_attempts = contracts.max_attempts_from_budget(budget)
    bind_role_name = may_start_workflow(wdoc, set(roles)) if wdoc else None
    ctx = AdmissionContext(
        org_id=org_id,
        actor=actor,
        actor_roles=roles,
        seat_name=seat_name,
        seat_state=seat_state,
        workflow_name=workflow_name,
        instance_id=None,
        pack_version_id=str(pack_version_id),
        pack_published=pack_status == "published",
        task_id=None,
        attempts_used=0,
        max_attempts=max_attempts,
        has_live_attempt=False,
        dependency_versions={},
        contract_dependency_versions={},
        reservation_usd=reservation,
        participant_ok=bind_role_name is not None,
        live_seat_attempts=await count_live_seat_attempts(conn, org_id, seat_name),
    )
    refusal = await check_admission(conn, ctx)
    if refusal:
        return refusal
    if seat_state != "ACTIVE":
        raise InstanceError("not_found", 404, "Seat not found", f"No active seat {seat_name!r}.")
    if seat_doc is None:
        raise InstanceError("not_found", 404, "Seat definition missing", f"Seat {seat_name!r} not on pack.")

    try:
        contracts.verify_pinned_pack_on_disk(packs_dir, pack_name, pack_ver, pack_digest)
    except PackMaterialError as exc:
        raise _pack_material_error(exc) from exc

    prefix = (wdoc.get("spec") or {}).get("id_prefix", "JOB")
    if simulation_instance_id is not None and "-SIM-" not in simulation_instance_id:
        raise InstanceError("internal", 500, "Invalid simulation id", "Simulated job ids contain -SIM-.")
    instance_id = simulation_instance_id or await ids.next_instance_id(conn, prefix)
    task_id = ids.new_task_id()
    attempt_id = ids.new_attempt_id()
    participant_role = bind_role_name
    if participant_role is None:
        raise InstanceError("internal", 500, "Admission inconsistency", "Start role binding missing.")
    repeat_from = (repeat_from_instance_id or "").strip() or None
    seed_artifact_type: str | None = None
    if repeat_from:
        await _assert_repeat_source(
            conn,
            org_id=org_id,
            actor=actor,
            starter_role=participant_role,
            workflow_name=workflow_name,
            repeat_from_instance_id=repeat_from,
        )
        seed_artifact_type = _intake_view_artifact_type(wdoc)
        if not seed_artifact_type:
            raise InstanceError(
                "conflict",
                409,
                "Cannot repeat",
                "This workflow has no initial artifact to copy.",
            )
    initial_state = (wdoc.get("spec") or {}).get("initial")
    assist_skill = resolve_assist_skill(seat_doc, wdoc, str(initial_state))
    skill_doc = defs.get("Skill", {}).get(assist_skill) or {}
    assist_work_type = (skill_doc.get("spec") or {}).get("work_types", ["analysis"])[0]
    try:
        contract = contracts.build_assist_contract(
            packs_dir=packs_dir,
            pack_name=pack_name,
            pack_version=pack_ver,
            pack_digest=pack_digest,
            defs=defs,
            org_id=org_id,
            instance_id=instance_id,
            task_id=task_id,
            seat_name=seat_name,
            seat_version=seat_version,
            seat_doc=seat_doc,
            workflow_name=workflow_name,
            skill_name=assist_skill,
            work_type=str(assist_work_type),
            participant_role=participant_role,
            person_id=actor,
            attempt_n=1,
            seat_limits=limits,
            org=org,
        )
    except PackMaterialError as exc:
        raise _pack_material_error(exc) from exc
    correlation_id = secrets.token_hex(16)
    intake_hints = (wdoc.get("spec") or {}).get("intake_hints") or []
    title = derive_job_title(first_message, hints=intake_hints if isinstance(intake_hints, list) else [])
    person_name = org.people[actor].name
    turn: dict[str, Any]
    try:
        async with conn.transaction():
            await conn.execute(
                "insert into work.instances ("
                " id, org_id, workflow, pack_version_id, seat, seat_version, title, state, created_by,"
                " idempotency_key, correlation_id"
                ") values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    instance_id,
                    org_id,
                    workflow_name,
                    pack_version_id,
                    seat_name,
                    seat_version,
                    title or workflow_name,
                    initial_state,
                    actor,
                    idempotency_key,
                    correlation_id,
                ),
            )
            await conn.execute(
                "insert into work.participants (instance_id, role, person_id, bound_by)"
                " values (%s, %s, %s, 'creation')",
                (instance_id, participant_role, actor),
            )
            await task_ops.insert_assist_task(
                conn,
                task_id=task_id,
                instance_id=instance_id,
                skill=assist_skill,
                work_type=str(assist_work_type),
                contract=contract,
                max_attempts=contracts.max_attempts_from_budget(contract["budget"]),
            )
            entry = await workflow_ops._create_entry_tasks(
                conn,
                packs_dir=packs_dir,
                org_id=org_id,
                instance_id=instance_id,
                seat_name=seat_name,
                seat_version=int(seat_version),
                workflow_name=workflow_name,
                pack_name=pack_name,
                pack_version=pack_ver,
                pack_digest=pack_digest,
                defs=defs,
                seat_doc=seat_doc,
                seat_limits=limits,
                entry_tasks=_state_tasks(wdoc, str(initial_state)),
                participants=[(participant_role, actor)],
                org=org,
            )
            if repeat_from and seed_artifact_type:
                seeded = await artifacts.seed_draft_from_prior_job(
                    conn,
                    source_instance_id=repeat_from,
                    target_instance_id=instance_id,
                    artifact_type=seed_artifact_type,
                    actor_person_id=actor,
                    prior_label=f"Copied from {repeat_from}",
                )
                if not seeded:
                    raise InstanceError(
                        "validation_failed",
                        422,
                        "Nothing to repeat",
                        "The prior job has no intake document to copy.",
                    )
                await conn.execute(
                    "update work.instances set attributes = attributes || %s::jsonb where id = %s",
                    (Jsonb({"repeat_from": repeat_from}), instance_id),
                )
            # The first state's Task working for the starter answers the first message; the assist Task waits for
            # later turns.
            intake = next((t for t in entry if t.person_id == actor), None)
            first_task_id = intake.task_id if intake else task_id
            first_reservation = float(intake.contract["budget"]["cost_usd"]) if intake else reservation
            turn = await insert_person_turn(
                conn,
                instance_id=instance_id,
                person_id=actor,
                text=first_message,
                client_turn_id=idempotency_key or ids.new_turn_id(),
            )
            await task_ops.admit_attempt(
                conn,
                org_id=org_id,
                seat=seat_name,
                daily_limit_usd=float(limits["daily_cost_usd"]),
                task_id=first_task_id,
                attempt_id=attempt_id,
                turn_id=turn["turn_id"],
                attempt_n=1,
                reservation_usd=first_reservation,
            )
            await conn.execute(
                "update work.turns set attempt_id = %s where id = %s",
                (attempt_id, turn["turn_id"]),
            )
            turn["attempt_id"] = attempt_id
            await write_execution_event(
                conn,
                ExecutionEventWrite(
                    org_id=org_id,
                    run_id=instance_id,
                    event_type="RunCreated",
                    actor_kind="person",
                    actor_id=actor,
                    correlation_id=correlation_id,
                    redacted_summary=f"Started job {instance_id}",
                    task_id=first_task_id,
                    attempt_id=attempt_id,
                ),
            )
            turn_payload = {
                "turn_id": turn["turn_id"],
                "seq": turn["seq"],
                "author": {"kind": "person", "id": actor, "name": person_name},
                "blocks": turn["blocks"],
                "at": turn["at"],
                "attempt_id": attempt_id,
            }
            outbox_rows = [
                OutboxRow(
                    stream=ids.stream_user(actor),
                    event_type="instance.created",
                    instance_id=instance_id,
                    audience={"person_id": actor},
                    data={"instance_id": instance_id, "title": title, "workflow": workflow_name},
                ),
                OutboxRow(
                    stream=ids.stream_instance(instance_id),
                    event_type="turn.created",
                    instance_id=instance_id,
                    audience={"roles": [participant_role]},
                    data={"instance_id": instance_id, "turn": turn_payload},
                ),
            ]
            seqs = await append_outbox_many(conn, outbox_rows)
    except pg_errors.UniqueViolation as exc:
        if _is_instance_idempotency_violation(exc):
            raced = await _idempotent_instance_id(conn, org_id, actor, idempotency_key)
            if raced:
                return await build_snapshot(conn, org, org_id, raced, actor)
            raise
        refusal = await _refusal_from_admit_backstop(conn, ctx, exc)
        if refusal:
            return refusal
        raise
    except pg_errors.CheckViolation as exc:
        refusal = await _refusal_from_admit_backstop(conn, ctx, exc)
        if refusal:
            return refusal
        raise
    cursor = ids.ui_event_cursor(ids.stream_instance(instance_id), seqs[ids.stream_instance(instance_id)])
    snap = await build_snapshot(conn, org, org_id, instance_id, actor)
    snap["cursor"] = cursor
    return snap


async def start_from_intake_message(
    conn: AsyncConnection,
    org: OrgModel,
    *,
    org_id: str,
    actor: str,
    roles: list[str],
    message: str,
    idempotency_key: str | None,
    packs_dir: Path,
    repeat_from_instance_id: str | None = None,
    seat_hint: str | None = None,
) -> dict[str, Any] | CommittedRefusal:
    workers = await list_digital_workers(conn, org, org_id, actor, roles)
    if seat_hint:
        workers = [w for w in workers if w["seat"] == seat_hint]
    if not workers:
        raise InstanceError(
            "not_permitted",
            403,
            "No colleague available",
            "No active digital employee is available for your account.",
        )
    seat_name, workflow_name = route_intake_message(message, workers)
    if not workflow_name:
        raise InstanceError(
            "conflict",
            409,
            "Nothing to start",
            "No workflow is configured for the available colleagues.",
        )
    return await start_instance(
        conn,
        org,
        org_id=org_id,
        actor=actor,
        roles=roles,
        seat_name=seat_name,
        workflow_name=workflow_name,
        first_message=message,
        idempotency_key=idempotency_key,
        packs_dir=packs_dir,
        repeat_from_instance_id=repeat_from_instance_id,
    )


async def _conversation_task(conn: AsyncConnection, instance_id: str, person_id: str) -> tuple | None:
    """A workflow Task working for this person that is in the conversation: waiting for their input, or running an
    attempt that answers one of their turns. Its turns go to it instead of the assist Task."""
    cur = await conn.execute(
        "select t.id, t.template, t.state, t.contract, t.attempts_used, t.max_attempts,"
        " exists(select 1 from work.attempts a where a.task_id = t.id and a.state in ('ADMITTED', 'CLAIMED')"
        "        and a.turn_id is not null)"
        " from work.tasks t"
        " where t.instance_id = %s and t.kind = 'task' and t.state in ('WAITING_INPUT', 'RUNNING')"
        " and t.contract->'on_behalf_of'->>'person_id' = %s"
        " order by case when t.template = 'request_intake' then 0 else 1 end, t.created_at, t.id"
        " for update of t",
        (instance_id, person_id),
    )
    for row in await cur.fetchall():
        state, in_conversation = row[2], bool(row[6])
        if state == "WAITING_INPUT" or in_conversation:
            return row
    return None


async def _post_turn_to_task(
    conn: AsyncConnection,
    org: OrgModel,
    task_row: tuple,
    *,
    org_id: str,
    instance_id: str,
    actor: str,
    roles: list[str],
    my_roles: list[str],
    text: str,
    client_turn_id: str,
    seat_name: str,
    seat_state: str,
    workflow_name: str,
    pack_version_id: str,
    pack_published: bool,
    attributes: dict[str, Any],
) -> dict[str, Any] | CommittedRefusal:
    """Resume a Task waiting for this person's input with their turn (a fresh attempt on a new thread whose context
    has the turn), or hold the turn for the Task's running attempt to read."""
    task_id, template, task_state, contract_json, attempts_used, max_attempts, _ = task_row
    contract = contract_json if isinstance(contract_json, dict) else json.loads(contract_json)
    if task_state != "WAITING_INPUT":
        await insert_person_turn(
            conn,
            instance_id=instance_id,
            person_id=actor,
            text=text,
            client_turn_id=client_turn_id,
            attempt_id=None,
        )
        row = await find_turn_by_client_id(conn, instance_id, actor, client_turn_id)
        assert row is not None
        turn_payload = project_turn(row, person_name=org.people[actor].name)
        await append_outbox_many(
            conn,
            [
                OutboxRow(
                    stream=ids.stream_instance(instance_id),
                    event_type="turn.created",
                    instance_id=instance_id,
                    audience={"roles": my_roles},
                    data={"instance_id": instance_id, "turn": turn_payload},
                )
            ],
        )
        return {"turn": turn_payload, "attempt_id": None}

    # Each answer gives the Task a fresh set of retries: its attempt budget counts failures, not questions asked.
    budget = contract.get("budget") or {}
    resume_max = int(attempts_used) + contracts.max_attempts_from_budget(budget)
    reservation = float(budget.get("cost_usd", 0.0))
    ctx = AdmissionContext(
        org_id=org_id,
        actor=actor,
        actor_roles=roles,
        seat_name=seat_name,
        seat_state=seat_state,
        workflow_name=workflow_name,
        instance_id=instance_id,
        pack_version_id=pack_version_id,
        pack_published=pack_published,
        task_id=task_id,
        attempts_used=int(attempts_used),
        max_attempts=max(int(max_attempts), resume_max),
        has_live_attempt=False,
        dependency_versions=attributes,
        contract_dependency_versions=contract.get("dependency_versions") or {},
        reservation_usd=reservation,
        participant_ok=True,
        live_seat_attempts=await count_live_seat_attempts(conn, org_id, seat_name),
    )
    refusal = await check_admission(conn, ctx)
    if refusal:
        return refusal

    defs = await _load_definitions(conn, pack_version_id)
    seat_doc = defs.get("Seat", {}).get(seat_name) or {}
    attempt_id = ids.new_attempt_id()
    try:
        async with conn.transaction():
            await conn.execute(
                "update work.tasks set max_attempts = %s, updated_at = now() where id = %s",
                (ctx.max_attempts, task_id),
            )
            turn_row = await insert_person_turn(
                conn,
                instance_id=instance_id,
                person_id=actor,
                text=text,
                client_turn_id=client_turn_id,
                attempt_id=None,
            )
            await task_ops.admit_attempt(
                conn,
                org_id=org_id,
                seat=seat_name,
                daily_limit_usd=float(_seat_limits(seat_doc)["daily_cost_usd"]),
                task_id=task_id,
                attempt_id=attempt_id,
                turn_id=turn_row["turn_id"],
                attempt_n=int(attempts_used) + 1,
                reservation_usd=reservation,
            )
            await conn.execute(
                "update work.turns set attempt_id = %s where id = %s",
                (attempt_id, turn_row["turn_id"]),
            )
            row = await find_turn_by_client_id(conn, instance_id, actor, client_turn_id)
            assert row is not None
            turn_payload = project_turn(row, person_name=org.people[actor].name)
            await append_outbox_many(
                conn,
                [
                    OutboxRow(
                        stream=ids.stream_instance(instance_id),
                        event_type="turn.created",
                        instance_id=instance_id,
                        audience={"roles": my_roles},
                        data={"instance_id": instance_id, "turn": turn_payload},
                    ),
                    OutboxRow(
                        stream=ids.stream_instance(instance_id),
                        event_type="task.state_changed",
                        instance_id=instance_id,
                        audience={"roles": my_roles},
                        data={
                            "instance_id": instance_id,
                            "task_id": task_id,
                            "template": template,
                            "from": "WAITING_INPUT",
                            "to": "RUNNING",
                        },
                    ),
                ],
            )
    except (pg_errors.CheckViolation, pg_errors.UniqueViolation) as exc:
        refusal = await _refusal_from_admit_backstop(conn, ctx, exc)
        if refusal:
            return refusal
        raise
    return {"turn": turn_payload, "attempt_id": attempt_id}


def _text_from_turn_blocks(blocks: Any) -> str:
    if not isinstance(blocks, list):
        return ""
    parts: list[str] = []
    for block in blocks:
        if isinstance(block, dict) and block.get("kind") == "text":
            parts.append(str(block.get("text") or ""))
    return " ".join(parts).strip()


async def _thread_indicates_request_detail(
    conn: AsyncConnection,
    instance_id: str,
    message: str,
    wdoc: dict[str, Any],
) -> bool:
    if message_indicates_request_detail(message, wdoc):
        return True
    cur = await conn.execute(
        "select blocks from work.turns where instance_id = %s and author_kind = 'person' order by seq",
        (instance_id,),
    )
    for row in await cur.fetchall():
        blocks = row[0]
        if message_indicates_request_detail(_text_from_turn_blocks(blocks), wdoc):
            return True
    return False


async def _apply_detail_signal_if_needed(
    conn: AsyncConnection,
    org: OrgModel,
    *,
    instance_id: str,
    instance_state: str,
    attributes: dict[str, Any],
    workflow_name: str,
    pack_version_id: str,
    message: str,
    packs_dir: Path,
) -> tuple[str, dict[str, Any]]:
    if instance_state != "conversation":
        return instance_state, attributes
    if int(attributes.get("detail_signal") or 0) > 0:
        return instance_state, attributes
    defs = await _load_definitions(conn, pack_version_id)
    wdoc = defs.get("WorkflowDefinition", {}).get(workflow_name) or {}
    pcur = await conn.execute(
        "select count(*) from work.turns where instance_id = %s and author_kind = 'person'",
        (instance_id,),
    )
    person_turns = int((await pcur.fetchone() or (0,))[0])
    # Stay in casual assist until at least one reply cycle (handoff jobs start with one person turn).
    if person_turns < 2:
        return instance_state, attributes
    if not await _thread_indicates_request_detail(conn, instance_id, message, wdoc):
        return instance_state, attributes
    new_attrs = {**attributes, "detail_signal": 1}
    await conn.execute(
        "update work.instances set attributes = %s where id = %s",
        (Jsonb(new_attrs), instance_id),
    )
    from .events import evaluate_attribute_triggers

    await evaluate_attribute_triggers(
        conn,
        org,
        instance_id,
        changed={"detail_signal"},
        packs_dir=packs_dir,
    )
    cur = await conn.execute(
        "select state, attributes from work.instances where id = %s",
        (instance_id,),
    )
    row = await cur.fetchone()
    if row is None:
        return instance_state, new_attrs
    st = str(row[0])
    att = row[1] if isinstance(row[1], dict) else json.loads(row[1] or "{}")
    return st, att


async def post_turn(
    conn: AsyncConnection,
    org: OrgModel,
    *,
    org_id: str,
    instance_id: str,
    actor: str,
    roles: list[str],
    text: str,
    client_turn_id: str,
    packs_dir: Path,
) -> dict[str, Any] | CommittedRefusal:
    my_roles = await _participant_roles(conn, instance_id, actor)
    if not my_roles:
        raise InstanceError("not_permitted", 403, "Not a participant", "You are not part of this job.")

    existing = await find_turn_by_client_id(conn, instance_id, actor, client_turn_id)
    if existing:
        pname = org.people[actor].name
        turn = project_turn(existing, person_name=pname)
        return {"turn": turn, "attempt_id": existing[6]}

    cur = await conn.execute(
        "select i.seat, i.seat_version, i.workflow, i.pack_version_id, i.attributes, i.correlation_id, i.state"
        " from work.instances i where i.id = %s and i.org_id = %s",
        (instance_id, org_id),
    )
    inst = await cur.fetchone()
    if inst is None:
        raise InstanceError("not_found", 404, "Job not found", f"No instance {instance_id!r}.")
    seat_name, seat_version, workflow_name, pvid, attributes, correlation_id, instance_state = inst
    attributes = attributes if isinstance(attributes, dict) else json.loads(attributes or "{}")

    instance_state, attributes = await _apply_detail_signal_if_needed(
        conn,
        org,
        instance_id=instance_id,
        instance_state=str(instance_state),
        attributes=attributes,
        workflow_name=str(workflow_name),
        pack_version_id=str(pvid),
        message=text,
        packs_dir=packs_dir,
    )

    scur = await conn.execute(
        "select state from registry.seats"
        " where org_id = %s and name = %s and version = %s for update",
        (org_id, seat_name, seat_version),
    )
    seat_locked = await scur.fetchone()
    if seat_locked is None:
        raise InstanceError("not_found", 404, "Seat not found", f"Seat {seat_name!r} v{seat_version} missing.")
    seat_state = seat_locked[0]
    pack_name, pack_ver, pack_digest, pack_status = await _pack_meta(conn, org_id, str(pvid))
    if seat_state != "ACTIVE":
        ctx = AdmissionContext(
            org_id=org_id,
            actor=actor,
            actor_roles=roles,
            seat_name=seat_name,
            seat_state=seat_state,
            workflow_name=workflow_name,
            instance_id=instance_id,
            pack_version_id=str(pvid),
            pack_published=pack_status == "published",
            task_id=None,
            attempts_used=0,
            max_attempts=1,
            has_live_attempt=False,
            dependency_versions=attributes,
            contract_dependency_versions={},
            reservation_usd=0.0,
            participant_ok=True,
            live_seat_attempts=0,
        )
        refusal = await check_admission(conn, ctx)
        if refusal:
            return refusal
        raise InstanceError("not_found", 404, "Seat not found", f"Seat {seat_name!r} is not active.")

    conv = await _conversation_task(conn, instance_id, actor)
    if conv is not None:
        return await _post_turn_to_task(
            conn,
            org,
            conv,
            org_id=org_id,
            instance_id=instance_id,
            actor=actor,
            roles=roles,
            my_roles=my_roles,
            text=text,
            client_turn_id=client_turn_id,
            seat_name=seat_name,
            seat_state=seat_state,
            workflow_name=workflow_name,
            pack_version_id=str(pvid),
            pack_published=pack_status == "published",
            attributes=attributes,
        )

    if str(instance_state) == "intake" and "requester" in my_roles:
        raise InstanceError(
            "conflict",
            409,
            "Brief is still updating",
            "Send another message with any missing detail, or open Documents to review the draft.",
        )

    tcur = await conn.execute(
        "select id, contract, attempts_used, max_attempts from work.tasks"
        " where instance_id = %s and kind = 'assist' limit 1 for update",
        (instance_id,),
    )
    task_row = await tcur.fetchone()
    if task_row is None:
        raise InstanceError("internal", 500, "Assist task missing", "This job has no assist task.")
    task_id, contract_json, attempts_used, max_attempts = task_row
    contract = contract_json if isinstance(contract_json, dict) else json.loads(contract_json)
    reservation = float(contract["budget"]["cost_usd"])
    tstate_cur = await conn.execute("select state from work.tasks where id = %s", (task_id,))
    task_state_before = (await tstate_cur.fetchone() or ("RUNNING",))[0]
    has_live = await task_has_live_attempt(conn, task_id)

    if has_live:
        await insert_person_turn(
            conn,
            instance_id=instance_id,
            person_id=actor,
            text=text,
            client_turn_id=client_turn_id,
            attempt_id=None,
        )
        row = await find_turn_by_client_id(conn, instance_id, actor, client_turn_id)
        assert row is not None
        turn_payload = project_turn(row, person_name=org.people[actor].name)
        await append_outbox_many(
            conn,
            [
                OutboxRow(
                    stream=ids.stream_instance(instance_id),
                    event_type="turn.created",
                    instance_id=instance_id,
                    audience={"roles": my_roles},
                    data={"instance_id": instance_id, "turn": turn_payload},
                )
            ],
        )
        return {"turn": turn_payload, "attempt_id": None}

    live = await count_live_seat_attempts(conn, org_id, seat_name)
    ctx = AdmissionContext(
        org_id=org_id,
        actor=actor,
        actor_roles=roles,
        seat_name=seat_name,
        seat_state=seat_state,
        workflow_name=workflow_name,
        instance_id=instance_id,
        pack_version_id=str(pvid),
        pack_published=pack_status == "published",
        task_id=task_id,
        attempts_used=int(attempts_used),
        max_attempts=int(max_attempts),
        turn_attempts_used=0,
        has_live_attempt=False,
        dependency_versions=attributes,
        contract_dependency_versions=contract.get("dependency_versions") or {},
        reservation_usd=reservation,
        participant_ok=True,
        live_seat_attempts=live,
    )
    refusal = await check_admission(conn, ctx)
    if refusal:
        return refusal

    defs = await _load_definitions(conn, str(pvid))
    seat_doc = defs.get("Seat", {}).get(seat_name) or {}
    wdoc = defs.get("WorkflowDefinition", {}).get(workflow_name) or {}
    try:
        contracts.verify_pinned_pack_on_disk(packs_dir, pack_name, pack_ver, pack_digest)
    except PackMaterialError as exc:
        raise _pack_material_error(exc) from exc
    assist_skill = resolve_assist_skill(seat_doc, wdoc, str(instance_state))
    skill_doc = defs.get("Skill", {}).get(assist_skill) or {}
    assist_work_type = (skill_doc.get("spec") or {}).get("work_types", ["analysis"])[0]
    participant_role = my_roles[0]
    attempt_n = int(attempts_used) + 1
    draft = contracts.build_assist_contract(
        packs_dir=packs_dir,
        pack_name=pack_name,
        pack_version=pack_ver,
        pack_digest=pack_digest,
        defs=defs,
        org_id=org_id,
        instance_id=instance_id,
        task_id=task_id,
        seat_name=seat_name,
        seat_version=int(seat_version),
        seat_doc=seat_doc,
        workflow_name=workflow_name,
        skill_name=assist_skill,
        work_type=str(assist_work_type),
        participant_role=participant_role,
        person_id=actor,
        attempt_n=attempt_n,
        seat_limits=_seat_limits(seat_doc),
        org=org,
    )
    contract = finalize_assist_contract(draft, previous=contract)
    reservation = float(contract["budget"]["cost_usd"])

    attempt_id = ids.new_attempt_id()
    daily_limit = float(_seat_limits(seat_doc)["daily_cost_usd"])
    try:
        async with conn.transaction():
            stored_contract = contract_json if isinstance(contract_json, dict) else json.loads(contract_json)
            if contract.get("contract_hash") != stored_contract.get("contract_hash"):
                await task_ops.update_assist_task_contract(
                    conn,
                    task_id=task_id,
                    skill=assist_skill,
                    work_type=str(assist_work_type),
                    contract=contract,
                )
            turn = await insert_person_turn(
                conn,
                instance_id=instance_id,
                person_id=actor,
                text=text,
                client_turn_id=client_turn_id,
                attempt_id=None,
            )
            await task_ops.admit_attempt(
                conn,
                org_id=org_id,
                seat=seat_name,
                daily_limit_usd=daily_limit,
                task_id=task_id,
                attempt_id=attempt_id,
                turn_id=turn["turn_id"],
                attempt_n=attempt_n,
                reservation_usd=reservation,
            )
            await conn.execute(
                "update work.turns set attempt_id = %s where id = %s",
                (attempt_id, turn["turn_id"]),
            )
            row = await find_turn_by_client_id(conn, instance_id, actor, client_turn_id)
            assert row is not None
            turn_payload = project_turn(row, person_name=org.people[actor].name)
            outbox_rows = [
                OutboxRow(
                    stream=ids.stream_instance(instance_id),
                    event_type="turn.created",
                    instance_id=instance_id,
                    audience={"roles": my_roles},
                    data={"instance_id": instance_id, "turn": turn_payload},
                )
            ]
            if task_state_before == "WAITING_INPUT":
                outbox_rows.append(
                    OutboxRow(
                        stream=ids.stream_instance(instance_id),
                        event_type="task.state_changed",
                        instance_id=instance_id,
                        audience={"roles": my_roles},
                        data={
                            "instance_id": instance_id,
                            "task_id": task_id,
                            "template": "assist",
                            "from": "WAITING_INPUT",
                            "to": "RUNNING",
                        },
                    )
                )
            await append_outbox_many(conn, outbox_rows)
    except (pg_errors.CheckViolation, pg_errors.UniqueViolation) as exc:
        refusal = await _refusal_from_admit_backstop(conn, ctx, exc)
        if refusal:
            return refusal
        raise
    else:
        return {"turn": turn_payload, "attempt_id": attempt_id}


async def list_turns_page(
    conn: AsyncConnection,
    org: OrgModel,
    org_id: str,
    instance_id: str,
    person_id: str,
    *,
    before_seq: int | None,
    limit: int,
) -> list[dict[str, Any]]:
    my_roles = await _participant_roles(conn, instance_id, person_id)
    if not my_roles:
        raise InstanceError("not_permitted", 403, "Not a participant", "You are not part of this job.")
    return await _fetch_turns(
        conn, org, instance_id, my_roles, limit=limit, before_seq=before_seq
    )
