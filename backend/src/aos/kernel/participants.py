"""Participant binding: queue, claim and by-rule resolution (M2-BE-03)."""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any

from psycopg import AsyncConnection

from aos.registry.kinds import Participant, WorkflowDefinition

from . import audit_store, clock, ids
from .org import OrgModel

_TEAM_OWNER_RULE = re.compile(r"^team_owner\(([a-z0-9_]+/[a-z0-9_]+)\)$")


class ParticipantError(Exception):
    def __init__(self, code: str, status: int, title: str, detail: str = "", **extra: Any) -> None:
        self.code = code
        self.status = status
        self.title = title
        self.detail = detail
        self.extra = extra
        super().__init__(title)


def caller_team(org: OrgModel, person_id: str) -> str:
    person = org.people.get(person_id)
    if person is None:
        raise ParticipantError("not_permitted", 403, "Unknown person", f"No person {person_id!r}.")
    return person.team


def team_display_name(org: OrgModel, team_path: str) -> str:
    dept_id, team_id = team_path.split("/", 1)
    dept = org.departments.get(dept_id)
    if dept is None:
        return team_path
    team = dept.teams.get(team_id)
    return team.name if team else team_path


def parse_team_owner_rule(rule: str) -> str | None:
    m = _TEAM_OWNER_RULE.match((rule or "").strip())
    return m.group(1) if m else None


def eval_participant_rule(org: OrgModel, rule: str) -> str:
    team_path = parse_team_owner_rule(rule)
    if team_path is None:
        raise ParticipantError(
            "validation_failed",
            422,
            "Unknown participant rule",
            f"Rule {rule!r} is not supported.",
        )
    dept_id, team_id = team_path.split("/", 1)
    dept = org.departments.get(dept_id)
    if dept is None or team_id not in dept.teams:
        raise ParticipantError(
            "validation_failed",
            422,
            "Unknown team in rule",
            f"No team {team_path!r} in the organization.",
        )
    owner = dept.teams[team_id].owner
    if owner not in org.people:
        raise ParticipantError("internal", 500, "Team owner missing", f"Owner {owner!r} is not a person.")
    return owner


async def _load_workflow(
    conn: AsyncConnection, instance_id: str
) -> tuple[str, str, WorkflowDefinition, str]:
    cur = await conn.execute(
        "select org_id, workflow, pack_version_id, status from work.instances where id = %s",
        (instance_id,),
    )
    row = await cur.fetchone()
    if row is None:
        raise ParticipantError("not_found", 404, "Job not found", f"No instance {instance_id!r}.")
    org_id, workflow_name, pack_version_id, status = row[0], row[1], str(row[2]), row[3]
    cur = await conn.execute(
        "select spec from registry.definitions where pack_version_id = %s and kind = 'WorkflowDefinition'"
        " and name = %s",
        (pack_version_id, workflow_name),
    )
    wrow = await cur.fetchone()
    if wrow is None:
        raise ParticipantError("internal", 500, "Workflow missing", "Pinned workflow definition not found.")
    wdoc = wrow[0] if isinstance(wrow[0], dict) else json.loads(wrow[0])
    return org_id, workflow_name, WorkflowDefinition.model_validate(wdoc), pack_version_id


def _by_claim_roles_for_queue(definition: WorkflowDefinition, queue_path: str) -> list[tuple[str, Participant]]:
    out: list[tuple[str, Participant]] = []
    for role, spec in definition.spec.participants.items():
        if spec.bind == "by_claim" and spec.queue == queue_path:
            out.append((role, spec))
    return out


async def _role_bound(conn: AsyncConnection, instance_id: str, role: str) -> bool:
    cur = await conn.execute(
        "select 1 from work.participants where instance_id = %s and role = %s limit 1",
        (instance_id, role),
    )
    return await cur.fetchone() is not None


async def _bound_person(conn: AsyncConnection, instance_id: str, role: str) -> str | None:
    cur = await conn.execute(
        "select person_id from work.participants where instance_id = %s and role = %s",
        (instance_id, role),
    )
    row = await cur.fetchone()
    return row[0] if row else None


async def _state_label(conn: AsyncConnection, pack_version_id: str, workflow_name: str, state: str) -> str:
    cur = await conn.execute(
        "select spec from registry.definitions where pack_version_id = %s and kind = 'WorkflowDefinition'"
        " and name = %s",
        (pack_version_id, workflow_name),
    )
    row = await cur.fetchone()
    if row is None:
        return state
    wdoc = row[0] if isinstance(row[0], dict) else json.loads(row[0])
    states = (wdoc.get("spec") or {}).get("states") or {}
    return str((states.get(state) or {}).get("label") or state)


async def _emit_participant_bound(
    conn: AsyncConnection,
    *,
    org: OrgModel,
    instance_id: str,
    role: str,
    person_id: str,
    bound_by: str,
) -> None:
    from .outbox import OutboxRow, append_outbox_many

    roles_cur = await conn.execute(
        "select role from work.participants where instance_id = %s order by role",
        (instance_id,),
    )
    roles = [r[0] for r in await roles_cur.fetchall()]
    name = org.people[person_id].name if person_id in org.people else person_id
    data = {
        "instance_id": instance_id,
        "role": role,
        "person_id": person_id,
        "name": name,
        "bound_by": bound_by,
    }
    await append_outbox_many(
        conn,
        [
            OutboxRow(
                stream=ids.stream_instance(instance_id),
                event_type="participant.bound",
                instance_id=instance_id,
                audience={"roles": roles},
                data=data,
            ),
        ],
    )


async def resolve_participant(
    conn: AsyncConnection,
    org: OrgModel,
    instance_id: str,
    role: str,
    *,
    packs_dir: Path | None = None,
) -> str | None:
    """Return the person bound to a workflow role, binding by-rule participants on first need."""
    _ = packs_dir  # reserved for future pack extensions
    person_id = await _bound_person(conn, instance_id, role)
    if person_id is not None:
        return person_id
    _org_id, _wf_name, definition, _pvid = await _load_workflow(conn, instance_id)
    spec = definition.spec.participants.get(role)
    if spec is None:
        return None
    if spec.bind == "by_rule":
        if not spec.rule:
            raise ParticipantError("internal", 500, "Participant misconfigured", f"Role {role!r} has no rule.")
        owner = eval_participant_rule(org, spec.rule)
        # ON CONFLICT, not try/except: a unique violation would abort the caller's whole transaction.
        ins = await conn.execute(
            "insert into work.participants (instance_id, role, person_id, bound_by)"
            " values (%s, %s, %s, 'rule') on conflict (instance_id, role) do nothing returning person_id",
            (instance_id, role, owner),
        )
        if await ins.fetchone() is None:
            return await _bound_person(conn, instance_id, role)
        await _emit_participant_bound(
            conn,
            org=org,
            instance_id=instance_id,
            role=role,
            person_id=owner,
            bound_by="rule",
        )
        return owner
    if spec.bind == "by_claim" and spec.queue:
        # The person who started the job is often the only member of the queue that
        # does the next step. Bind them so the job does not wait for someone else.
        holder = await _sole_queue_member_on_job(conn, org, instance_id, spec.queue)
        if holder is None:
            return None
        ins = await conn.execute(
            "insert into work.participants (instance_id, role, person_id, bound_by)"
            " values (%s, %s, %s, 'claim') on conflict (instance_id, role) do nothing returning person_id",
            (instance_id, role, holder),
        )
        if await ins.fetchone() is None:
            return await _bound_person(conn, instance_id, role)
        await _emit_participant_bound(
            conn,
            org=org,
            instance_id=instance_id,
            role=role,
            person_id=holder,
            bound_by="claim",
        )
        return holder
    return None


async def _sole_queue_member_on_job(
    conn: AsyncConnection,
    org: OrgModel,
    instance_id: str,
    queue_path: str,
) -> str | None:
    cur = await conn.execute(
        "select distinct person_id from work.participants where instance_id = %s",
        (instance_id,),
    )
    members: list[str] = []
    for (person_id,) in await cur.fetchall():
        person = org.people.get(person_id)
        if person is not None and person.team == queue_path:
            members.append(person_id)
    if len(members) == 1:
        return members[0]
    return None


async def list_queue_instances(
    conn: AsyncConnection,
    org: OrgModel,
    org_id: str,
    person_id: str,
    queue_path: str,
) -> list[dict[str, Any]]:
    if caller_team(org, person_id) != queue_path:
        raise ParticipantError(
            "not_permitted",
            403,
            "Not your queue",
            "You can only list the queue for your own team.",
        )
    queue_label = team_display_name(org, queue_path)
    cur = await conn.execute(
        "select id, title, workflow, pack_version_id, state, version, created_at, state_entered_at"
        " from work.instances where org_id = %s and status = 'running'"
        " order by created_at desc",
        (org_id,),
    )
    now = clock.now()
    items: list[dict[str, Any]] = []
    for row in await cur.fetchall():
        inst_id, title, workflow_name, pvid, state, version, created_at, state_entered_at = row
        _oid, _wn, definition, _pv = await _load_workflow(conn, inst_id)
        claim_roles = _by_claim_roles_for_queue(definition, queue_path)
        if not claim_roles:
            continue
        claim_role = None
        for role, _spec in claim_roles:
            if not await _role_bound(conn, inst_id, role):
                claim_role = role
                break
        if claim_role is None:
            continue
        state_label = await _state_label(conn, str(pvid), workflow_name, state)
        elapsed = int((now - state_entered_at).total_seconds()) if state_entered_at else 0
        items.append(
            {
                "instance_id": inst_id,
                "title": title,
                "workflow": workflow_name,
                "state": state,
                "state_label": state_label,
                "version": version,
                "requester": None,
                "buyer": None,
                "waiting_on": {"kind": "queue", "label": queue_label, "person_id": None},
                "time_in_state_s": elapsed,
                "started_at": created_at.isoformat(),
                "last_activity_at": state_entered_at.isoformat(),
                "claim_role": claim_role,
            }
        )
    return items


_NOTE_LIMIT = 2000


def _review_note(decision: str, note: str | None) -> str:
    if decision not in ("approve", "reject"):
        raise ParticipantError(
            "validation_failed", 422, "Unknown decision", "Choose approve or reject."
        )
    text = (note or "").strip()
    if len(text) > _NOTE_LIMIT:
        raise ParticipantError(
            "validation_failed", 422, "Comment is too long", "Keep the comment under 2000 characters."
        )
    if decision == "reject" and not text:
        raise ParticipantError(
            "validation_failed", 422, "Comment required", "Write a comment to reject this request."
        )
    return text


async def _post_review_comment(
    conn: AsyncConnection,
    org: OrgModel,
    instance_id: str,
    person_id: str,
    text: str,
) -> None:
    from .conversation import insert_person_turn
    from .outbox import OutboxRow, append_outbox_many

    turn = await insert_person_turn(
        conn,
        instance_id=instance_id,
        person_id=person_id,
        text=text,
        client_turn_id=str(uuid.uuid4()),
    )
    name = org.people[person_id].name if person_id in org.people else person_id
    payload = {
        "turn_id": turn["turn_id"],
        "seq": turn["seq"],
        "author": {"kind": "person", "id": person_id, "name": name},
        "blocks": turn["blocks"],
        "at": turn["at"],
        "attempt_id": turn["attempt_id"],
    }
    await append_outbox_many(
        conn,
        [
            OutboxRow(
                stream=ids.stream_instance(instance_id),
                event_type="turn.created",
                instance_id=instance_id,
                audience={},
                data={"instance_id": instance_id, "turn": payload},
            )
        ],
    )


async def _reject_from_queue(
    conn: AsyncConnection,
    org: OrgModel,
    org_id: str,
    person_id: str,
    instance_id: str,
    role: str,
    current_version: int,
    comment: str,
) -> dict[str, Any]:
    from .decisions import _emit_pending_resolved

    ts = clock.now()
    upd = await conn.execute(
        "update work.instances set status = 'cancelled', closed_at = %s, version = version + 1"
        " where id = %s and version = %s returning version",
        (ts, instance_id, current_version),
    )
    row = await upd.fetchone()
    if row is None:
        raise ParticipantError(
            "stale_version", 409, "Job changed", "Reload the job and try again.", current_version=current_version
        )
    await conn.execute(
        "update work.tasks set state = 'CANCELLED', updated_at = %s"
        " where instance_id = %s and state not in ('COMPLETED', 'FAILED', 'CANCELLED', 'EXCEPTION')",
        (ts, instance_id),
    )
    await conn.execute(
        "update work.attempts set state = 'ENDED', outcome = 'cancelled', ended_at = %s"
        " where state in ('ADMITTED', 'CLAIMED')"
        " and task_id in (select id from work.tasks where instance_id = %s)",
        (ts, instance_id),
    )
    await conn.execute(
        "update work.timers set status = 'cancelled' where instance_id = %s and status = 'scheduled'",
        (instance_id,),
    )
    pend = await conn.execute(
        "select id, for_person_id from work.pending_items where instance_id = %s and status = 'open'",
        (instance_id,),
    )
    open_items = await pend.fetchall()
    await conn.execute(
        "update work.pending_items set status = 'voided', resolved_at = %s, resolved_by = %s"
        " where instance_id = %s and status = 'open'",
        (ts, person_id, instance_id),
    )
    for pending_id, for_person in open_items:
        if for_person:
            await _emit_pending_resolved(
                conn,
                instance_id=instance_id,
                person_id=str(for_person),
                pending_id=str(pending_id),
                outcome="voided",
                by=person_id,
            )
    await _post_review_comment(conn, org, instance_id, person_id, f"Rejected. {comment}")
    await audit_store.record(
        conn,
        org_id=org_id,
        actor=person_id,
        action="participant.queue_rejected",
        subject=f"instance:{instance_id}",
        data={"role": role, "note": comment, "version": int(row[0])},
    )
    return {"instance_id": instance_id, "decision": "rejected", "note": comment}


async def claim_instance(
    conn: AsyncConnection,
    org: OrgModel,
    org_id: str,
    person_id: str,
    instance_id: str,
    role: str,
    expected_version: int,
    *,
    packs_dir: Path,
    decision: str = "approve",
    note: str | None = None,
) -> dict[str, Any]:
    from . import decisions as decision_ops
    from . import instances as instance_ops

    cur = await conn.execute(
        "select org_id, version, status from work.instances where id = %s for update",
        (instance_id,),
    )
    row = await cur.fetchone()
    if row is None:
        raise ParticipantError("not_found", 404, "Job not found", f"No instance {instance_id!r}.")
    inst_org, current_version, inst_status = row[0], int(row[1]), row[2]
    if inst_org != org_id:
        raise ParticipantError("not_found", 404, "Job not found", f"No instance {instance_id!r}.")
    if inst_status != "running":
        raise ParticipantError("conflict", 409, "Job not open", "This job is no longer running.")

    _oid, _wf_name, definition, _pvid = await _load_workflow(conn, instance_id)
    spec = definition.spec.participants.get(role)
    if spec is None or spec.bind != "by_claim":
        raise ParticipantError(
            "validation_failed",
            422,
            "Role cannot be claimed",
            f"{role!r} is not a queue role on this workflow.",
        )
    if not spec.queue or caller_team(org, person_id) != spec.queue:
        raise ParticipantError(
            "not_permitted",
            403,
            "Not on this queue",
            "Your team is not the queue for this role.",
        )
    # A queue member who already has another role (they started the job) still takes
    # this queue role. Someone off the queue is refused above.
    if await _role_bound(conn, instance_id, role):
        raise ParticipantError(
            "already_claimed",
            409,
            "Role already claimed",
            "Someone else claimed this role first.",
            current_version=current_version,
        )

    if int(expected_version) != current_version:
        raise ParticipantError(
            "stale_version",
            409,
            "Job changed",
            "Reload the job and try again.",
            current_version=current_version,
        )

    comment = _review_note(decision, note)
    if decision == "reject":
        return await _reject_from_queue(
            conn, org, org_id, person_id, instance_id, role, current_version, comment
        )

    # ON CONFLICT, not try/except: a unique violation would abort the transaction before we could answer.
    ins = await conn.execute(
        "insert into work.participants (instance_id, role, person_id, bound_by)"
        " values (%s, %s, %s, 'claim') on conflict (instance_id, role) do nothing returning person_id",
        (instance_id, role, person_id),
    )
    if await ins.fetchone() is None:
        raise ParticipantError(
            "already_claimed",
            409,
            "Role already claimed",
            "Someone else claimed this role first.",
            current_version=current_version,
        )

    upd = await conn.execute(
        "update work.instances set version = version + 1 where id = %s and version = %s"
        " returning version",
        (instance_id, current_version),
    )
    new_row = await upd.fetchone()
    if new_row is None:
        raise ParticipantError(
            "stale_version",
            409,
            "Job changed",
            "Reload the job and try again.",
            current_version=current_version,
        )
    new_version = int(new_row[0])

    await audit_store.record(
        conn,
        org_id=org_id,
        actor=person_id,
        action="participant.claim",
        subject=f"instance:{instance_id}",
        data={"role": role, "version": new_version},
    )

    from .outbox import OutboxRow, append_outbox_many

    inst_cur = await conn.execute(
        "select title, workflow from work.instances where id = %s",
        (instance_id,),
    )
    inst_meta = await inst_cur.fetchone()
    title = inst_meta[0] if inst_meta else ""
    workflow_name = inst_meta[1] if inst_meta else ""
    await _emit_participant_bound(
        conn,
        org=org,
        instance_id=instance_id,
        role=role,
        person_id=person_id,
        bound_by="claim",
    )
    await append_outbox_many(
        conn,
        [
            OutboxRow(
                stream=ids.stream_user(person_id),
                event_type="instance.created",
                instance_id=instance_id,
                audience={"person_id": person_id},
                data={"instance_id": instance_id, "title": title, "workflow": workflow_name},
            ),
        ],
    )

    if comment:
        await _post_review_comment(conn, org, instance_id, person_id, f"Approved. {comment}")
    await decision_ops.open_ready_decisions(conn, instance_id, org=org, packs_dir=packs_dir)
    return await instance_ops.build_snapshot(conn, org, org_id, instance_id, person_id)
