"""Console operate reads: workflows, instances, timeline (M2-BE-06)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from psycopg import AsyncConnection

from aos.registry.kinds import EFFECT_COMMIT_WORK_TYPES, WorkflowDefinition

from . import clock
from .org import CONSOLE_ROLES, OrgModel
from .participants import _state_label


class ConsoleError(Exception):
    def __init__(self, code: str, status: int, title: str, detail: str = "", **extra: Any) -> None:
        self.code = code
        self.status = status
        self.title = title
        self.detail = detail
        self.extra = extra
        super().__init__(title)


def _caller_may_operate_workflow(
    *,
    workflow_owner: str | None,
    person_id: str,
    roles: list[str],
    console: bool,
) -> bool:
    if workflow_owner and person_id == workflow_owner:
        return True
    if console and CONSOLE_ROLES & set(roles):
        return True
    return False


def _require_workflow_access(
    *,
    workflow_owner: str | None,
    person_id: str,
    roles: list[str],
    console: bool,
) -> None:
    if not _caller_may_operate_workflow(
        workflow_owner=workflow_owner, person_id=person_id, roles=roles, console=console
    ):
        raise ConsoleError(
            "not_permitted",
            403,
            "Not allowed",
            "You need the workflow owner or a Console role.",
        )


async def _load_definitions(conn: AsyncConnection, pack_version_id: str) -> dict[str, dict[str, dict]]:
    from .workflow import _load_definitions as load

    return await load(conn, pack_version_id)


def _tool_actions_index(defs: dict[str, dict[str, dict]]) -> dict[str, tuple[str, str, str]]:
    """Map native tool name -> (resource, action, class)."""
    out: dict[str, tuple[str, str, str]] = {}
    for prov_name, prov in defs.get("ToolProvider", {}).items():
        for tname, tool in (prov.get("spec") or {}).get("tools", {}).items():
            resource = str(tool.get("resource") or "")
            action = str(tool.get("action") or "")
            tclass = str(tool.get("class") or tool.get("tool_class") or "read")
            out[tname] = (resource, action, tclass)
    return out


def _gate_approval_actions(defs: dict[str, dict[str, dict]], workflow_name: str) -> set[str]:
    actions: set[str] = set()
    for pol in defs.get("Policy", {}).values():
        spec = pol.get("spec") or {}
        if spec.get("type") != "gate_rules" or spec.get("workflow") != workflow_name:
            continue
        for rule in spec.get("rules") or []:
            if rule.get("effect") == "REQUIRE_APPROVAL" and rule.get("action"):
                actions.add(str(rule["action"]))
    return actions


def _needs_approval(
    *,
    work_type: str,
    skill_name: str,
    defs: dict[str, dict[str, dict]],
    workflow_name: str,
) -> bool:
    if work_type not in EFFECT_COMMIT_WORK_TYPES:
        return False
    skill = (defs.get("Skill") or {}).get(skill_name) or {}
    may_request = (skill.get("spec") or {}).get("may_request") or []
    tools = _tool_actions_index(defs)
    gated = _gate_approval_actions(defs, workflow_name)
    for tname in may_request:
        meta = tools.get(tname)
        if meta is None:
            continue
        resource, action, tclass = meta
        if tclass != "committed_effect":
            continue
        candidate = f"{resource}.{action}"
        if candidate in gated:
            return True
    return False


def _transition_on_list(on: str | list[str]) -> list[str]:
    return [on] if isinstance(on, str) else list(on)


def _stage_target_seconds(defs: dict[str, dict[str, dict]], state: str) -> int | None:
    pack = next(iter((defs.get("Pack") or {}).values()), None)
    if pack is None:
        return None
    targets = ((pack.get("spec") or {}).get("observability") or {}).get("stage_targets") or {}
    raw = targets.get(state)
    if not raw:
        return None
    try:
        return int(clock.parse_duration(str(raw)).total_seconds())
    except ValueError:
        return None


async def _published_workflow_row(
    conn: AsyncConnection,
    org_id: str,
    workflow_name: str,
    *,
    definition_version: int | None,
) -> tuple[str, dict[str, Any], int]:
    if definition_version is not None:
        cur = await conn.execute(
            "select d.pack_version_id, d.spec, (d.spec->'metadata'->>'version')::int"
            " from registry.definitions d"
            " join registry.pack_versions pv on pv.id = d.pack_version_id"
            " where pv.org_id = %s and pv.status = 'published'"
            " and d.kind = 'WorkflowDefinition' and d.name = %s"
            " and (d.spec->'metadata'->>'version')::int = %s"
            " order by pv.version desc limit 1",
            (org_id, workflow_name, definition_version),
        )
    else:
        cur = await conn.execute(
            "select d.pack_version_id, d.spec, (d.spec->'metadata'->>'version')::int"
            " from registry.definitions d"
            " join registry.pack_versions pv on pv.id = d.pack_version_id"
            " where pv.org_id = %s and pv.status = 'published'"
            " and d.kind = 'WorkflowDefinition' and d.name = %s"
            " order by pv.version desc, (d.spec->'metadata'->>'version')::int desc limit 1",
            (org_id, workflow_name),
        )
    row = await cur.fetchone()
    if row is None:
        raise ConsoleError("not_found", 404, "Workflow not found", f"No published workflow {workflow_name!r}.")
    pvid, spec, ver = row[0], row[1], int(row[2])
    doc = spec if isinstance(spec, dict) else json.loads(spec)
    return str(pvid), doc, ver


async def list_workflows(conn: AsyncConnection, org_id: str) -> list[dict[str, Any]]:
    cur = await conn.execute(
        "select distinct on (d.name) d.name,"
        " (d.spec->'metadata'->>'version')::int,"
        " d.spec->'spec'->>'title'"
        " from registry.definitions d"
        " join registry.pack_versions pv on pv.id = d.pack_version_id"
        " where pv.org_id = %s and pv.status = 'published' and d.kind = 'WorkflowDefinition'"
        " order by d.name, pv.version desc, (d.spec->'metadata'->>'version')::int desc",
        (org_id,),
    )
    rows = await cur.fetchall()
    running_cur = await conn.execute(
        "select workflow, count(*) from work.instances"
        " where org_id = %s and status = 'running' group by workflow",
        (org_id,),
    )
    running = {r[0]: int(r[1]) for r in await running_cur.fetchall()}
    return [
        {
            "name": name,
            "version": version,
            "title": title or name,
            "running": running.get(name, 0),
        }
        for name, version, title in rows
    ]


async def get_workflow_graph(
    conn: AsyncConnection,
    org_id: str,
    workflow_name: str,
    *,
    person_id: str,
    roles: list[str],
    console: bool,
    version: int | None,
) -> dict[str, Any]:
    pvid, wdoc, wver = await _published_workflow_row(conn, org_id, workflow_name, definition_version=version)
    owner = (wdoc.get("metadata") or {}).get("owner")
    _require_workflow_access(
        workflow_owner=str(owner) if owner else None,
        person_id=person_id,
        roles=roles,
        console=console,
    )
    definition = WorkflowDefinition.model_validate(wdoc)
    defs = await _load_definitions(conn, pvid)
    pack = next(iter((defs.get("Pack") or {}).values()), {})
    stage_targets = ((pack.get("spec") or {}).get("observability") or {}).get("stage_targets") or {}
    spec = definition.spec
    states_out: list[dict[str, Any]] = []
    for name, st in spec.states.items():
        tasks_out = []
        for tmpl in st.tasks:
            tasks_out.append(
                {
                    "template": tmpl.template,
                    "skill": tmpl.skill,
                    "verifier": tmpl.verifier,
                    "needs_approval": _needs_approval(
                        work_type=tmpl.work_type,
                        skill_name=tmpl.skill,
                        defs=defs,
                        workflow_name=workflow_name,
                    ),
                }
            )
        on_event = {
            ev: {
                "template": t.template,
                "skill": t.skill,
                "verifier": t.verifier,
                "needs_approval": _needs_approval(
                    work_type=t.work_type,
                    skill_name=t.skill,
                    defs=defs,
                    workflow_name=workflow_name,
                ),
            }
            for ev, t in st.on_event.items()
        }
        states_out.append(
            {
                "name": name,
                "label": st.label,
                "final": st.final,
                "tasks": tasks_out,
                "on_event": on_event,
            }
        )
    transitions = [
        {
            "from": tr.from_,
            "to": tr.to,
            "on": _transition_on_list(tr.on),
            "by": tr.by,
            "guard": tr.guard,
            "effects": tr.effects,
        }
        for tr in spec.transitions
    ]
    parallel = [
        {
            "on": pr.on,
            "region": pr.region,
            "start": {
                "template": pr.start.template,
                "skill": pr.start.skill,
                "verifier": pr.start.verifier,
                "needs_approval": _needs_approval(
                    work_type=pr.start.work_type,
                    skill_name=pr.start.skill,
                    defs=defs,
                    workflow_name=workflow_name,
                ),
            },
            "join_at": pr.join_at,
            "join_guard": pr.join_guard,
        }
        for pr in spec.parallel
    ]
    timers = {k: v.model_dump(by_alias=True) for k, v in spec.timers.items()}
    participants = {
        role: part.model_dump(mode="json", by_alias=True)
        for role, part in spec.participants.items()
    }
    return {
        "name": workflow_name,
        "version": wver,
        "title": spec.title,
        "initial": spec.initial,
        "states": states_out,
        "transitions": transitions,
        "parallel": parallel,
        "timers": timers,
        "participants": participants,
        "stage_targets": stage_targets,
    }


def _week_start() -> datetime:
    now = clock.now()
    start = now - timedelta(days=now.weekday())
    return start.replace(hour=0, minute=0, second=0, microsecond=0)


async def _waiting_on(
    conn: AsyncConnection,
    org: OrgModel,
    instance_id: str,
) -> dict[str, Any]:
    pend = await conn.execute(
        "select for_person_id, title from work.pending_items"
        " where instance_id = %s and status = 'open' and for_person_id is not null"
        " order by created_at limit 1",
        (instance_id,),
    )
    prow = await pend.fetchone()
    if prow is not None:
        pid, title = prow[0], prow[1]
        name = org.people[pid].name if pid in org.people else pid
        return {"kind": "person", "label": title or name, "person_id": pid}

    task_cur = await conn.execute(
        "select 1 from work.tasks where instance_id = %s"
        " and state in ('READY', 'RUNNING', 'VERIFYING') limit 1",
        (instance_id,),
    )
    has_task = await task_cur.fetchone() is not None

    timer_cur = await conn.execute(
        "select name from work.timers where instance_id = %s and status = 'scheduled' limit 1",
        (instance_id,),
    )
    timer_row = await timer_cur.fetchone()
    if timer_row is not None and not has_task:
        pend_any = await conn.execute(
            "select 1 from work.pending_items where instance_id = %s and status = 'open' limit 1",
            (instance_id,),
        )
        if await pend_any.fetchone() is None:
            return {"kind": "timer", "label": str(timer_row[0]).replace("_", " "), "person_id": None}

    if has_task:
        return {"kind": "task", "label": "Agent task", "person_id": None}

    return {"kind": "nothing", "label": "", "person_id": None}


def _waiting_kind(waiting: dict[str, Any]) -> str:
    return str(waiting.get("kind") or "nothing")


async def _summary_row(
    conn: AsyncConnection,
    org: OrgModel,
    org_id: str,
    row: tuple[Any, ...],
) -> dict[str, Any]:
    (
        inst_id,
        title,
        workflow_name,
        pvid,
        state,
        version,
        created_at,
        closed_at,
        inst_status,
        state_entered_at,
    ) = row
    now = clock.now()
    elapsed = int((now - state_entered_at).total_seconds()) if state_entered_at else 0
    defs = await _load_definitions(conn, str(pvid))
    target_s = _stage_target_seconds(defs, state)
    state_label = await _state_label(conn, str(pvid), workflow_name, state)
    waiting = await _waiting_on(conn, org, inst_id)
    out: dict[str, Any] = {
        "instance_id": inst_id,
        "title": title,
        "workflow": workflow_name,
        "state": state,
        "state_label": state_label,
        "version": version,
        "requester": None,
        "buyer": None,
        "waiting_on": waiting,
        "time_in_state_s": elapsed,
        "started_at": created_at.isoformat(),
        "closed_at": closed_at.isoformat() if closed_at else None,
        "last_activity_at": (state_entered_at or created_at).isoformat(),
    }
    if target_s is not None:
        out["stage_target_s"] = target_s
    return out


async def list_instances(
    conn: AsyncConnection,
    org: OrgModel,
    org_id: str,
    *,
    state: str | None,
    workflow: str | None,
    waiting_on: str | None,
    q: str | None,
) -> dict[str, Any]:
    cur = await conn.execute(
        "select id, title, workflow, pack_version_id, state, version, created_at, closed_at, status,"
        " state_entered_at"
        " from work.instances where org_id = %s order by created_at desc",
        (org_id,),
    )
    rows = await cur.fetchall()
    items: list[dict[str, Any]] = []
    week_start = _week_start()
    summary = {"running": 0, "waiting_on_person": 0, "over_target": 0, "closed_this_week": 0}
    for row in rows:
        inst_status = row[8]
        if inst_status == "running":
            summary["running"] += 1
        closed_at = row[7]
        if inst_status in ("closed", "cancelled") and closed_at and closed_at >= week_start:
            summary["closed_this_week"] += 1
        item = await _summary_row(conn, org, org_id, row)
        if item.get("stage_target_s") is not None and item["time_in_state_s"] > item["stage_target_s"]:
            summary["over_target"] += 1
        if _waiting_kind(item["waiting_on"]) == "person":
            summary["waiting_on_person"] += 1

        if state and item["state"] != state:
            continue
        if workflow and item["workflow"] != workflow:
            continue
        if waiting_on and _waiting_kind(item["waiting_on"]) != waiting_on:
            continue
        if q:
            needle = q.strip().lower()
            if needle and needle not in item["instance_id"].lower() and needle not in item["title"].lower():
                continue
        items.append(item)
    return {"summary": summary, "items": items}


def _event_label(definition: WorkflowDefinition, event: str) -> str:
    if event.startswith("decision."):
        name = event.removeprefix("decision.")
        dec = (definition.spec.decisions or {}).get(name)
        if dec is not None:
            return dec.label
    if event.startswith("task.completed."):
        return f"Task {event.removeprefix('task.completed.')} completed"
    if event.startswith("timer."):
        return f"Timer {event.removeprefix('timer.')} fired"
    return event.replace("_", " ").replace(".", " ")


async def get_instance_timeline(
    conn: AsyncConnection,
    org: OrgModel,
    org_id: str,
    instance_id: str,
    *,
    person_id: str,
    roles: list[str],
    console: bool,
) -> dict[str, Any]:
    cur = await conn.execute(
        "select id, title, workflow, pack_version_id, state, created_at, state_entered_at"
        " from work.instances where id = %s and org_id = %s",
        (instance_id, org_id),
    )
    row = await cur.fetchone()
    if row is None:
        raise ConsoleError("not_found", 404, "Job not found", f"No instance {instance_id!r}.")
    _, _title, workflow_name, pvid, _state, created_at, _state_entered = row
    pvid = str(pvid)
    wcur = await conn.execute(
        "select spec from registry.definitions where pack_version_id = %s and kind = 'WorkflowDefinition'"
        " and name = %s",
        (pvid, workflow_name),
    )
    wrow = await wcur.fetchone()
    if wrow is None:
        raise ConsoleError("internal", 500, "Workflow missing", "Pinned workflow definition not found.")
    wdoc = wrow[0] if isinstance(wrow[0], dict) else json.loads(wrow[0])
    owner = (wdoc.get("metadata") or {}).get("owner")
    _require_workflow_access(
        workflow_owner=str(owner) if owner else None,
        person_id=person_id,
        roles=roles,
        console=console,
    )
    definition = WorkflowDefinition.model_validate(wdoc)
    defs = await _load_definitions(conn, pvid)
    part_cur = await conn.execute(
        "select role from work.participants where instance_id = %s and person_id = %s",
        (instance_id, person_id),
    )
    viewer_roles = [r[0] for r in await part_cur.fetchall()] or list(roles)

    tcur = await conn.execute(
        "select from_state, to_state, event, guard, at, instance_version"
        " from work.instance_transitions where instance_id = %s order by instance_version",
        (instance_id,),
    )
    transitions = await tcur.fetchall()
    initial = definition.spec.initial
    stages: list[dict[str, Any]] = []
    now = clock.now()

    if not transitions:
        target_s = _stage_target_seconds(defs, initial)
        entered = created_at
        stages.append(
            {
                "state": initial,
                "entered_at": entered.isoformat(),
                "left_at": None,
                "duration_s": int((now - entered).total_seconds()),
                "target_s": target_s,
            }
        )
    else:
        first_from = transitions[0][0]
        if first_from != initial:
            initial = first_from
        entered = created_at
        left = transitions[0][4]
        target_s = _stage_target_seconds(defs, initial)
        stages.append(
            {
                "state": initial,
                "entered_at": entered.isoformat(),
                "left_at": left.isoformat(),
                "duration_s": int((left - entered).total_seconds()),
                "target_s": target_s,
            }
        )
        for idx, (from_st, to_st, _ev, _guard, at, _ver) in enumerate(transitions):
            nxt = transitions[idx + 1][4] if idx + 1 < len(transitions) else None
            target = _stage_target_seconds(defs, to_st)
            end = nxt or now
            stages.append(
                {
                    "state": to_st,
                    "entered_at": at.isoformat(),
                    "left_at": nxt.isoformat() if nxt else None,
                    "duration_s": int((end - at).total_seconds()),
                    "target_s": target,
                }
            )

    entries: list[dict[str, Any]] = []
    for from_st, to_st, event, guard, at, ver in transitions:
        to_label = definition.spec.states[to_st].label if to_st in definition.spec.states else to_st
        detail = f"Moved from {from_st} to {to_st}."
        if guard:
            detail += f" Guard: {guard}."
        entries.append(
            {
                "at": at.isoformat(),
                "kind": "transition",
                "title": f"Entered {to_label}",
                "detail": detail,
                "refs": {"event": event, "instance_version": str(ver)},
            }
        )

    dcur = await conn.execute(
        "select id, event, value, actor, actor_role, at"
        " from gov.decision_records"
        " where subject_kind = 'instance' and subject_id = %s order by at",
        (instance_id,),
    )
    for did, event, value, actor, actor_role, at in await dcur.fetchall():
        actor_name = org.people[actor].name if actor in org.people else actor
        entries.append(
            {
                "at": at.isoformat(),
                "kind": "decision",
                "title": _event_label(definition, event),
                "detail": f"{actor_name} chose {value}." if value else f"{actor_name} recorded a decision.",
                "actor": actor_name,
                "refs": {"decision_id": did, "role": actor_role or ""},
            }
        )

    pcur = await conn.execute(
        "select id, kind, title, status, created_at, resolved_at, resolved_by"
        " from work.pending_items where instance_id = %s order by created_at",
        (instance_id,),
    )
    for pid, kind, title, status, cat, rat, rby in await pcur.fetchall():
        entries.append(
            {
                "at": cat.isoformat(),
                "kind": "event",
                "title": title or f"{kind} opened",
                "detail": "Waiting for a person to decide.",
                "refs": {"pending_id": pid},
            }
        )
        if status == "resolved" and rat is not None:
            rname = org.people[rby].name if rby and rby in org.people else (rby or "")
            entries.append(
                {
                    "at": rat.isoformat(),
                    "kind": "event",
                    "title": f"{title or kind} resolved",
                    "detail": f"{rname} completed this step." if rname else "Completed.",
                    "actor": rname or None,
                    "refs": {"pending_id": pid},
                }
            )

    tmcur = await conn.execute(
        "select name, fired_at from work.timers where instance_id = %s and fired_at is not null order by fired_at",
        (instance_id,),
    )
    for name, fired_at in await tmcur.fetchall():
        entries.append(
            {
                "at": fired_at.isoformat(),
                "kind": "timer",
                "title": f"Timer {name.replace('_', ' ')} fired",
                "detail": "The deadline was reached.",
                "refs": {"timer": name},
            }
        )

    acur = await conn.execute(
        "select a.id, a.n, a.admitted_at, a.ended_at, t.template"
        " from work.attempts a join work.tasks t on t.id = a.task_id"
        " where t.instance_id = %s order by a.admitted_at, a.n",
        (instance_id,),
    )
    for aid, n, admitted_at, ended_at, template in await acur.fetchall():
        entries.append(
            {
                "at": admitted_at.isoformat(),
                "kind": "attempt",
                "title": f"Attempt {n} started for {template}",
                "detail": "The worker picked up the task.",
                "refs": {"attempt_id": aid, "template": template},
            }
        )
        if ended_at is not None:
            entries.append(
                {
                    "at": ended_at.isoformat(),
                    "kind": "attempt",
                    "title": f"Attempt {n} ended for {template}",
                    "detail": "The attempt finished.",
                    "refs": {"attempt_id": aid, "template": template},
                }
            )

    avcur = await conn.execute(
        "select av.artifact_id, av.version, a.artifact_type, av.created_at,"
        " av.produced_by_kind, av.produced_by, a.name"
        " from work.artifact_versions av"
        " join work.artifacts a on a.id = av.artifact_id"
        " where a.instance_id = %s order by av.created_at",
        (instance_id,),
    )
    for aid, ver, atype, at, by_kind, by_id, aname in await avcur.fetchall():
        type_doc = (defs.get("ArtifactType") or {}).get(atype) or {}
        type_label = (type_doc.get("spec") or {}).get("title") or atype.replace("_", " ")
        by_label = ""
        if by_kind == "person" and by_id in org.people:
            by_label = org.people[by_id].name
        elif by_id:
            by_label = str(by_id)
        entries.append(
            {
                "at": at.isoformat(),
                "kind": "artifact",
                "title": f"{type_label} version {ver} saved",
                "detail": f"{aname} was updated." + (f" By {by_label}." if by_label else ""),
                "actor": by_label or None,
                "refs": {"artifact_id": aid, "version": str(ver)},
            }
        )
    entries.sort(key=lambda e: (e["at"], e.get("kind", "")))
    return {"instance_id": instance_id, "stages": stages, "entries": entries}
