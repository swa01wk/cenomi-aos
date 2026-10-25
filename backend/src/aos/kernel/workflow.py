"""Workflow FSM interpreter: matching, apply_event, effects (M2)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from .org import OrgModel

from psycopg import AsyncConnection

from aos.registry.expressions import ExpressionScope, evaluate
from aos.registry.kinds import TaskTemplate, Transition, WorkflowDefinition

from . import clock, contracts, ids
from . import tasks as task_ops
from .outbox import ExecutionEventWrite, OutboxRow, append_outbox_many, write_execution_event

TransitionReason = Literal["no_match", "wrong_role", "guard_failed", "not_running", "join_pending"]

_ALLOWED_ACTOR_KINDS = frozenset({"seat", "person", "kernel", "connector", "demo"})


class WorkflowEffectError(Exception):
    """An effect could not run; the surrounding transaction must roll back."""


@dataclass(frozen=True)
class TransitionMatch:
    transition: Transition | None
    reason: TransitionReason | None
    effects: list[dict[str, Any]]
    entry_tasks: list[TaskTemplate]


@dataclass(frozen=True)
class ApplyEventResult:
    applied: bool
    from_state: str
    to_state: str
    version: int
    reason: TransitionReason | None = None


def _build_scope(
    *,
    attributes: dict[str, Any],
    workflow_ctx: dict[str, Any],
    artifact_ctx: dict[str, Any] | None,
    subject_ctx: dict[str, Any] | None,
) -> ExpressionScope:
    scope: dict[str, dict[str, Any]] = {
        "attr": dict(attributes),
        "workflow": dict(workflow_ctx),
    }
    if artifact_ctx is not None:
        scope["artifact"] = dict(artifact_ctx)
    if subject_ctx is not None:
        scope["subject"] = dict(subject_ctx)
    return scope


def match_transition(
    definition: WorkflowDefinition,
    *,
    state: str,
    event: str,
    actor_role: str | None,
    attributes: dict[str, Any] | None = None,
    workflow_ctx: dict[str, Any] | None = None,
    artifact_ctx: dict[str, Any] | None = None,
    subject_ctx: dict[str, Any] | None = None,
) -> TransitionMatch:
    """Return the first transition that matches *state* and *event*, or why none fired."""
    spec = definition.spec
    attrs = attributes or {}
    wf_ctx = {**(workflow_ctx or {}), "state": state}
    scope = _build_scope(
        attributes=attrs,
        workflow_ctx=wf_ctx,
        artifact_ctx=artifact_ctx,
        subject_ctx=subject_ctx,
    )

    candidates: list[Transition] = []
    for tr in spec.transitions:
        if tr.from_ != state:
            continue
        if event not in tr.events:
            continue
        candidates.append(tr)

    if not candidates:
        return TransitionMatch(None, "no_match", [], [])

    role_blocked = False
    guard_blocked = False

    for tr in candidates:
        if tr.by is not None:
            if actor_role != tr.by:
                role_blocked = True
                continue
        if tr.guard is not None and not evaluate(tr.guard, scope):
            guard_blocked = True
            continue
        target = spec.states[tr.to]
        return TransitionMatch(tr, None, list(tr.effects), list(target.tasks))

    if guard_blocked:
        return TransitionMatch(None, "guard_failed", [], [])
    if role_blocked:
        return TransitionMatch(None, "wrong_role", [], [])
    return TransitionMatch(None, "no_match", [], [])


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


async def _participants(conn: AsyncConnection, instance_id: str) -> list[tuple[str, str]]:
    cur = await conn.execute(
        "select role, person_id from work.participants where instance_id = %s order by role",
        (instance_id,),
    )
    return [(r[0], r[1]) for r in await cur.fetchall()]


def _actor_fields(actor: dict[str, Any] | None) -> tuple[str, str]:
    if actor is None:
        return "kernel", "kernel"
    kind = str(actor.get("kind") or "kernel")
    if kind not in _ALLOWED_ACTOR_KINDS:
        raise ValueError(
            f"actor kind must be one of {sorted(_ALLOWED_ACTOR_KINDS)!r}, not {kind!r}"
        )
    actor_id = str(actor.get("id") or "kernel")
    return kind, actor_id


def _person_for_role(participants: list[tuple[str, str]], role: str) -> str | None:
    for r, person_id in participants:
        if r == role:
            return person_id
    return None


async def _create_entry_tasks(
    conn: AsyncConnection,
    *,
    packs_dir: Path,
    org_id: str,
    instance_id: str,
    seat_name: str,
    seat_version: int,
    workflow_name: str,
    pack_name: str,
    pack_version: int,
    pack_digest: str,
    defs: dict[str, dict[str, dict]],
    seat_doc: dict[str, Any],
    seat_limits: dict[str, Any],
    entry_tasks: list[TaskTemplate],
    participants: list[tuple[str, str]],
    org: "OrgModel | None" = None,
) -> None:
    if not entry_tasks:
        return
    for tpl in entry_tasks:
        if tpl.on_behalf_of is None:
            raise WorkflowEffectError(
                f"template {tpl.template!r} is missing on_behalf_of (participant role)"
            )
        role = tpl.on_behalf_of
        person_id = _person_for_role(participants, role)
        task_id = ids.new_task_id()
        contract = contracts.build_task_contract(
            packs_dir=packs_dir,
            pack_name=pack_name,
            pack_version=pack_version,
            pack_digest=pack_digest,
            defs=defs,
            org_id=org_id,
            instance_id=instance_id,
            task_id=task_id,
            seat_name=seat_name,
            seat_version=seat_version,
            seat_doc=seat_doc,
            workflow_name=workflow_name,
            template=tpl.model_dump(by_alias=True),
            participant_role=role,
            person_id=person_id,
            seat_limits=seat_limits,
            org=org,
        )
        await task_ops.insert_workflow_task(
            conn,
            task_id=task_id,
            instance_id=instance_id,
            template=tpl.template,
            skill=tpl.skill,
            work_type=tpl.work_type,
            verifier=tpl.verifier,
            contract=contract,
            max_attempts=contracts.max_attempts_from_budget(contract["budget"]),
        )


async def _run_effects(
    conn: AsyncConnection,
    *,
    org_id: str,
    instance_id: str,
    definition: WorkflowDefinition,
    effects: list[dict[str, Any]],
    participants: list[tuple[str, str]],
    at: Any,
) -> None:
    for effect in effects:
        if len(effect) != 1:
            raise WorkflowEffectError(f"effect must have one key, got {effect!r}")
        key, val = next(iter(effect.items()))
        if key == "start_timer":
            name = str(val)
            timer = definition.spec.timers.get(name)
            if timer is None:
                raise WorkflowEffectError(f"unknown timer {name!r}")
            cur = await conn.execute(
                "select coalesce(max(generation), 0) from work.timers"
                " where instance_id = %s and name = %s",
                (instance_id, name),
            )
            row = await cur.fetchone()
            generation = int(row[0]) + 1 if row else 1
            duration = timer.after
            if clock.demo_enabled() and timer.demo_after:
                duration = timer.demo_after
            fires_at = at + clock.parse_duration(duration)
            await conn.execute(
                "insert into work.timers (id, instance_id, name, emits, fires_at, generation)"
                " values (%s, %s, %s, %s, %s, %s)",
                (ids.new_timer_id(), instance_id, name, timer.emits, fires_at, generation),
            )
        elif key == "cancel_timers":
            await conn.execute(
                "update work.timers set status = 'cancelled'"
                " where instance_id = %s and status = 'scheduled'",
                (instance_id,),
            )
        elif key == "lock":
            artifact_type = str(val)
            cur = await conn.execute(
                "select id, latest_version from work.artifacts"
                " where instance_id = %s and artifact_type = %s"
                " order by latest_version desc limit 1",
                (instance_id, artifact_type),
            )
            row = await cur.fetchone()
            if row is None:
                raise WorkflowEffectError(f"no artifact of type {artifact_type!r} to lock")
            await conn.execute(
                "update work.artifacts set status = 'locked' where id = %s",
                (row[0],),
            )
        elif key == "handover":
            role = str(val)
            person_id = next((p for r, p in participants if r == role), None)
            if person_id is None:
                raise WorkflowEffectError(f"no participant bound for handover role {role!r}")
            await conn.execute(
                "insert into work.notifications (id, org_id, person_id, instance_id, text, at)"
                " values (%s, %s, %s, %s, %s, %s)",
                (
                    ids.new_notification_id(),
                    org_id,
                    person_id,
                    instance_id,
                    "Your job has finished. Review the outcome when you are ready.",
                    at,
                ),
            )
        elif key == "outcome_record":
            pass  # intent only; evidence.outcome_records in a later story
        elif key == "bind":
            raise WorkflowEffectError(f"unsupported effect {key!r} in this story")
        else:
            raise WorkflowEffectError(f"unknown effect {key!r}")


async def _state_changed_outbox(
    conn: AsyncConnection,
    *,
    instance_id: str,
    from_state: str,
    to_state: str,
    version: int,
    label: str | None,
    decision_id: str | None,
    participants: list[tuple[str, str]],
) -> None:
    roles = [r for r, _ in participants]
    data: dict[str, Any] = {
        "instance_id": instance_id,
        "from": from_state,
        "to": to_state,
        "version": version,
    }
    if label:
        data["label"] = label
    if decision_id is not None:
        data["decision_id"] = decision_id
    rows = [
        OutboxRow(
            stream=ids.stream_instance(instance_id),
            event_type="instance.state_changed",
            instance_id=instance_id,
            audience={"roles": roles},
            data=dict(data),
        ),
    ]
    seen: set[str] = set()
    for _role, person_id in participants:
        if person_id in seen:
            continue
        seen.add(person_id)
        rows.append(
            OutboxRow(
                stream=ids.stream_user(person_id),
                event_type="instance.state_changed",
                instance_id=instance_id,
                audience={"person_id": person_id},
                data=dict(data),
            ),
        )
    await append_outbox_many(conn, rows)


async def apply_event(
    conn: AsyncConnection,
    instance_id: str,
    event: str,
    *,
    by_role: str | None,
    decision_id: str | None = None,
    packs_dir: Path,
    org: "OrgModel",
    actor: dict[str, Any] | None = None,
) -> ApplyEventResult:
    """Match *event* against the pinned workflow and commit a transition or record why it was ignored."""
    actor_kind, actor_id = _actor_fields(actor)
    ts = clock.now()

    cur = await conn.execute(
        "select org_id, workflow, pack_version_id, seat, seat_version, state, version, status,"
        " attributes, correlation_id"
        " from work.instances where id = %s for update",
        (instance_id,),
    )
    row = await cur.fetchone()
    if row is None:
        raise ValueError(f"instance {instance_id!r} not found")
    (
        org_id,
        workflow_name,
        pack_version_id,
        seat_name,
        seat_version,
        from_state,
        version,
        inst_status,
        attributes_raw,
        correlation_id,
    ) = row
    attributes = attributes_raw if isinstance(attributes_raw, dict) else json.loads(attributes_raw or "{}")
    pack_cur = await conn.execute(
        "select pack_name, version, digest from registry.pack_versions where id = %s",
        (str(pack_version_id),),
    )
    pack_row = await pack_cur.fetchone()
    if pack_row is None:
        raise ValueError(f"pack version {pack_version_id!r} not found")
    pack_name, pack_ver, pack_digest = pack_row[0], int(pack_row[1]), pack_row[2]
    graph_revision = f"{pack_name}@{pack_ver}"

    defs = await _load_definitions(conn, str(pack_version_id))
    wdoc = defs.get("WorkflowDefinition", {}).get(workflow_name)
    if wdoc is None:
        raise ValueError(f"workflow {workflow_name!r} missing on pinned pack")
    definition = WorkflowDefinition.model_validate(wdoc)
    seat_doc = defs.get("Seat", {}).get(seat_name) or {}
    seat_limits = (seat_doc.get("spec") or {}).get("limits") or {}

    participants = await _participants(conn, instance_id)

    if inst_status != "running":
        await write_execution_event(
            conn,
            ExecutionEventWrite(
                org_id=org_id,
                run_id=instance_id,
                event_type="WorkflowEventIgnored",
                actor_kind=actor_kind,
                actor_id=actor_id,
                correlation_id=correlation_id,
                redacted_summary=f"Event {event} ignored (not_running) in {from_state}",
                graph_revision=graph_revision,
                attributes={"state": from_state, "event": event, "reason": "not_running"},
            ),
        )
        return ApplyEventResult(False, from_state, from_state, int(version), "not_running")

    match = match_transition(
        definition,
        state=from_state,
        event=event,
        actor_role=by_role,
        attributes=attributes,
    )

    if match.transition is None:
        reason = match.reason or "no_match"
        await write_execution_event(
            conn,
            ExecutionEventWrite(
                org_id=org_id,
                run_id=instance_id,
                event_type="WorkflowEventIgnored",
                actor_kind=actor_kind,
                actor_id=actor_id,
                correlation_id=correlation_id,
                redacted_summary=f"Event {event} ignored ({reason}) in {from_state}",
                graph_revision=graph_revision,
                attributes={"state": from_state, "event": event, "reason": reason},
            ),
        )
        return ApplyEventResult(False, from_state, from_state, int(version), reason)

    from . import regions as region_ops

    if region_ops.is_join_state(definition, from_state):
        if not await region_ops.join_ready(
            conn, instance_id, from_state, definition, attributes
        ):
            await write_execution_event(
                conn,
                ExecutionEventWrite(
                    org_id=org_id,
                    run_id=instance_id,
                    event_type="WorkflowEventIgnored",
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    correlation_id=correlation_id,
                    redacted_summary=f"Event {event} ignored (join_pending) in {from_state}",
                    graph_revision=graph_revision,
                    attributes={"state": from_state, "event": event, "reason": "join_pending"},
                ),
            )
            return ApplyEventResult(False, from_state, from_state, int(version), "join_pending")

    tr = match.transition
    to_state = tr.to
    new_version = int(version) + 1
    to_spec = definition.spec.states[to_state]
    to_label = to_spec.label

    if to_spec.final:
        await conn.execute(
            "update work.instances set state = %s, version = %s, state_entered_at = %s,"
            " status = 'closed', closed_at = %s where id = %s",
            (to_state, new_version, ts, ts, instance_id),
        )
    else:
        await conn.execute(
            "update work.instances set state = %s, version = %s, state_entered_at = %s where id = %s",
            (to_state, new_version, ts, instance_id),
        )
    await conn.execute(
        "insert into work.instance_transitions ("
        " instance_id, from_state, to_state, event, guard, decision_id, instance_version, at"
        ") values (%s, %s, %s, %s, %s, %s, %s, %s)",
        (instance_id, from_state, to_state, event, tr.guard, decision_id, new_version, ts),
    )
    await _create_entry_tasks(
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
        seat_limits=seat_limits,
        entry_tasks=match.entry_tasks,
        participants=participants,
        org=org,
    )
    await _run_effects(
        conn,
        org_id=org_id,
        instance_id=instance_id,
        definition=definition,
        effects=match.effects,
        participants=participants,
        at=ts,
    )
    await _state_changed_outbox(
        conn,
        instance_id=instance_id,
        from_state=from_state,
        to_state=to_state,
        version=new_version,
        label=to_label,
        decision_id=decision_id,
        participants=participants,
    )
    if region_ops.is_join_state(definition, from_state):
        await region_ops.mark_regions_joined(
            conn, instance_id, from_state, at=ts
        )
    if region_ops.is_join_state(definition, to_state):
        await region_ops.rerun_stale_regions(
            conn,
            instance_id,
            to_state,
            definition,
            attributes,
            packs_dir=packs_dir,
            org_id=org_id,
            seat_name=seat_name,
            seat_version=int(seat_version),
            workflow_name=workflow_name,
            pack_name=pack_name,
            pack_version=pack_ver,
            pack_digest=pack_digest,
            defs=defs,
            seat_doc=seat_doc,
            seat_limits=seat_limits,
            participants=participants,
            org=org,
        )
    guard_attr = tr.guard if tr.guard is not None else ""
    await write_execution_event(
        conn,
        ExecutionEventWrite(
            org_id=org_id,
            run_id=instance_id,
            event_type="StateTransitioned",
            actor_kind=actor_kind,
            actor_id=actor_id,
            correlation_id=correlation_id,
            redacted_summary=f"{from_state} → {to_state} on {event}",
            graph_revision=graph_revision,
            attributes={
                "from_state": from_state,
                "to_state": to_state,
                "event": event,
                "guard": guard_attr,
                "decision_id": decision_id or "",
                "instance_version": new_version,
            },
        ),
    )
    from . import decisions as decision_ops
    from . import task_retry as task_retry_ops

    await task_retry_ops.void_task_retry_on_state_leave(
        conn,
        instance_id=instance_id,
        from_state=from_state,
        definition=definition,
        job_closed=bool(to_spec.final),
    )
    await decision_ops.open_ready_decisions(conn, instance_id, org=org, packs_dir=packs_dir)
    return ApplyEventResult(True, from_state, to_state, new_version)
