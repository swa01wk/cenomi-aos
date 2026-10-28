"""Workflow simulation in a rolled-back transaction (M2-BE-06). Task attempts run through ``run_attempt`` (the real
graphs with the fake model, see ``aos.sim_worker``) when given, else through the stub."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from psycopg import AsyncConnection
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from aos.registry.kinds import WorkflowDefinition
from aos.registry.loader import load_pack

from . import clock, events, instances, participants, registry_store, timers, workflow
from .decisions import _apply_sets
from .org import OrgModel
from .regions import latest_artifact_version
from .seats import insert_seats_for_published_pack
from .simulate_stub import AttemptRunner, drain_instance_tasks


class SimulationRollback(Exception):
    """Carries the report out of a transaction that must not commit."""

    def __init__(self, report: dict[str, Any]) -> None:
        self.report = report
        super().__init__("simulation rollback")


@dataclass
class _SimContext:
    org: OrgModel
    org_id: str
    packs_dir: Path
    pack_version_id: str
    workflow_name: str
    instance_id: str | None = None
    path: list[str] | None = None
    tasks_created: int = 0
    dead_ends: list[str] | None = None
    sim_counter: int = 0
    run_attempt: AttemptRunner | None = None

    def __post_init__(self) -> None:
        if self.path is None:
            self.path = []
        if self.dead_ends is None:
            self.dead_ends = []


def _load_script(pack_root: Path, script_name: str) -> list[dict[str, Any]]:
    path = pack_root / "evals" / f"{script_name}.yaml"
    if not path.is_file() and not script_name.endswith(".yaml"):
        path = pack_root / "evals" / script_name
    doc = yaml.safe_load(path.read_text())
    events_list = doc.get("events") if isinstance(doc, dict) else None
    if not isinstance(events_list, list):
        raise ValueError(f"script {path} has no events list")
    return [e for e in events_list if isinstance(e, dict)]


def _event_type(step: dict[str, Any]) -> str:
    return str(step.get("type") or "")


def _script_attributes(step: dict[str, Any]) -> dict[str, Any]:
    raw = step.get("attributes")
    return dict(raw) if isinstance(raw, dict) else {}


async def _merge_free_attributes(
    conn: AsyncConnection,
    instance_id: str,
    attrs: dict[str, Any],
    *,
    org: OrgModel,
    packs_dir: Path,
) -> None:
    if not attrs:
        return
    cur = await conn.execute(
        "select attributes, pack_version_id from work.instances where id = %s for update",
        (instance_id,),
    )
    row = await cur.fetchone()
    if row is None:
        return
    existing = row[0] if isinstance(row[0], dict) else json.loads(row[0] or "{}")
    merged = {**existing, **attrs}
    await conn.execute(
        "update work.instances set attributes = %s where id = %s",
        (Jsonb(merged), instance_id),
    )
    from . import events as workflow_events

    await workflow_events.evaluate_attribute_triggers(
        conn,
        org,
        instance_id,
        changed=set(attrs.keys()),
        packs_dir=packs_dir,
    )


async def _apply_script_decision(
    conn: AsyncConnection,
    ctx: _SimContext,
    decision_name: str,
    script_attrs: dict[str, Any],
) -> None:
    inst = ctx.instance_id
    assert inst is not None
    cur = await conn.execute(
        "select workflow, pack_version_id, state, version, attributes from work.instances where id = %s for update",
        (inst,),
    )
    row = await cur.fetchone()
    if row is None:
        return
    workflow_name, pvid, _state, _ver, attributes_raw = row
    attributes = attributes_raw if isinstance(attributes_raw, dict) else json.loads(attributes_raw or "{}")
    wcur = await conn.execute(
        "select spec from registry.definitions where pack_version_id = %s and kind = 'WorkflowDefinition'"
        " and name = %s",
        (str(pvid), str(workflow_name)),
    )
    wdoc = (await wcur.fetchone())[0]
    definition = WorkflowDefinition.model_validate(wdoc if isinstance(wdoc, dict) else json.loads(wdoc))
    dec = definition.spec.decisions.get(decision_name)
    if dec is None:
        ctx.dead_ends.append(f"decision.{decision_name}: undefined")
        return

    view_type = definition.spec.states[dec.state].view
    artifact_version: int | None = None
    bound_content: dict[str, Any] | None = None
    if view_type:
        artifact_version = await latest_artifact_version(conn, inst, str(view_type))
        if artifact_version is not None:
            acur = await conn.execute(
                "select id from work.artifacts where instance_id = %s and artifact_type = %s and key = '' limit 1",
                (inst, str(view_type)),
            )
            aid_row = await acur.fetchone()
            if aid_row:
                vcur = await conn.execute(
                    "select content from work.artifact_versions where artifact_id = %s and version = %s",
                    (aid_row[0], artifact_version),
                )
                vrow = await vcur.fetchone()
                if vrow:
                    bound_content = vrow[0] if isinstance(vrow[0], dict) else json.loads(vrow[0])

    selection: list[str] | None = None
    for attr_key, setter in dec.sets.items():
        if setter == "selection_count":
            if attr_key in script_attrs:
                n = int(script_attrs[attr_key])
                selection = [f"sim-sel-{i}" for i in range(n)]
            elif bound_content and bound_content.get("rows"):
                rows = bound_content["rows"]
                key = None
                from aos.registry.kinds import ArtifactType

                raw_at = (await _load_defs(conn, str(pvid))).get("ArtifactType", {}).get(str(view_type))
                if raw_at:
                    at = ArtifactType.model_validate(raw_at)
                    key = at.spec.row_key or "id"
                selection = [
                    str(r.get(key or "id"))
                    for r in rows
                    if isinstance(r, dict) and (key or "id") in r
                ]

    new_attributes = _apply_sets(
        attributes,
        dec,
        artifact_version=artifact_version,
        selection=selection,
    )
    await conn.execute(
        "update work.instances set attributes = %s where id = %s",
        (Jsonb(new_attributes), inst),
    )
    from . import events as workflow_events

    changed = {k for k in dec.sets if attributes.get(k) != new_attributes.get(k)}
    await workflow_events.evaluate_attribute_triggers(
        conn,
        ctx.org,
        inst,
        changed=changed,
        packs_dir=ctx.packs_dir,
    )
    result = await workflow.apply_event(
        conn,
        inst,
        f"decision.{decision_name}",
        by_role=dec.for_,
        packs_dir=ctx.packs_dir,
        org=ctx.org,
        actor={"kind": "person", "id": script_attrs.get("actor") or "simulate"},
    )
    if not result.applied and result.reason:
        ctx.dead_ends.append(f"decision.{decision_name}: {result.reason}")
    await _track_state(conn, ctx)


async def _load_defs(conn: AsyncConnection, pvid: str) -> dict[str, dict[str, dict]]:
    return await workflow._load_definitions(conn, pvid)


async def _count_tasks(conn: AsyncConnection, instance_id: str) -> int:
    cur = await conn.execute(
        "select count(*) from work.tasks where instance_id = %s and kind = 'task'",
        (instance_id,),
    )
    return int((await cur.fetchone())[0])


async def _track_state(conn: AsyncConnection, ctx: _SimContext) -> None:
    if not ctx.instance_id:
        return
    cur = await conn.execute("select state from work.instances where id = %s", (ctx.instance_id,))
    row = await cur.fetchone()
    if row is None:
        return
    state = str(row[0])
    if not ctx.path or ctx.path[-1] != state:
        ctx.path.append(state)


async def _run_script(conn: AsyncConnection, ctx: _SimContext, steps: list[dict[str, Any]]) -> dict[str, Any]:
    pcur = await conn.execute(
        "select pack_name from registry.pack_versions where id = %s",
        (ctx.pack_version_id,),
    )
    pack_name = (await pcur.fetchone())[0]
    pack_root = registry_store.pack_root(ctx.packs_dir, pack_name)

    wcur = await conn.execute(
        "select spec from registry.definitions where pack_version_id = %s and kind = 'WorkflowDefinition'"
        " and name = %s",
        (ctx.pack_version_id, ctx.workflow_name),
    )
    wdoc = (await wcur.fetchone())[0]
    id_prefix = (wdoc.get("spec") or {}).get("id_prefix", "JOB")

    seat_name = _default_seat_for_workflow(pack_root, ctx.workflow_name)

    for step in steps:
        kind = _event_type(step)
        actor = str(step.get("actor") or "faisal")

        if kind == "seat_ui.new_job":
            ctx.sim_counter += 1
            sim_id = f"{id_prefix}-SIM-{ctx.sim_counter}"
            roles = list(ctx.org.people[actor].roles)
            result = await instances.start_instance(
                conn,
                ctx.org,
                org_id=ctx.org_id,
                actor=actor,
                roles=roles,
                seat_name=seat_name,
                workflow_name=ctx.workflow_name,
                first_message=str(step.get("text") or "Simulation job"),
                idempotency_key=f"sim-{sim_id}",
                packs_dir=ctx.packs_dir,
                simulation_instance_id=sim_id,
            )
            if isinstance(result, dict):
                ctx.instance_id = str(result["instance_id"])
                await _track_state(conn, ctx)
            await drain_instance_tasks(
                conn,
                org=ctx.org,
                org_id=ctx.org_id,
                instance_id=ctx.instance_id or sim_id,
                packs_dir=ctx.packs_dir,
                after_progress=lambda: _track_state(conn, ctx),
                run_attempt=ctx.run_attempt,
                dead_ends=ctx.dead_ends,
            )
            continue

        inst = ctx.instance_id
        if inst is None:
            ctx.dead_ends.append(f"{kind}: no job started")
            continue

        if kind == "claim":
            role = str(step.get("role") or "buyer")
            icur = await conn.execute("select version from work.instances where id = %s", (inst,))
            ver = int((await icur.fetchone())[0])
            await participants.claim_instance(
                conn,
                ctx.org,
                ctx.org_id,
                actor,
                inst,
                role,
                ver,
                packs_dir=ctx.packs_dir,
            )
        elif kind.startswith("event."):
            ename = kind.removeprefix("event.")
            fired = await events.raise_event(
                conn,
                ctx.org,
                inst,
                ename,
                packs_dir=ctx.packs_dir,
                trigger="simulate.script",
            )
            if not fired:
                ctx.dead_ends.append(f"{kind}: already raised")
        elif kind.startswith("decision."):
            dname = kind.removeprefix("decision.")
            await _apply_script_decision(conn, ctx, dname, {**_script_attributes(step), "actor": actor})
        elif kind.startswith("timer."):
            emits = kind.removeprefix("timer.")
            await _merge_free_attributes(conn, inst, _script_attributes(step), org=ctx.org, packs_dir=ctx.packs_dir)
            tcur = await conn.execute(
                "select id from work.timers where instance_id = %s and emits = %s and status = 'scheduled'"
                " order by fires_at desc limit 1",
                (inst, emits),
            )
            trow = await tcur.fetchone()
            if trow is None:
                ctx.dead_ends.append(f"{kind}: no scheduled timer")
            else:
                await conn.execute(
                    "update work.timers set fires_at = %s where id = %s",
                    (clock.now(), trow[0]),
                )
                await timers.process_due_timer(
                    conn,
                    str(trow[0]),
                    as_of=clock.now(),
                    org=ctx.org,
                    packs_dir=ctx.packs_dir,
                )
                await _track_state(conn, ctx)
        elif kind == "turn":
            text = str(step.get("text") or "")
            await instances.post_turn(
                conn,
                ctx.org,
                org_id=ctx.org_id,
                instance_id=inst,
                actor=actor,
                roles=list(ctx.org.people[actor].roles),
                text=text,
                client_turn_id=f"sim-turn-{steps.index(step)}",
                packs_dir=ctx.packs_dir,
            )
        elif kind == "mail.message_received":
            created = await events.raise_inbound_event(
                conn, ctx.org, inst, kind, packs_dir=ctx.packs_dir
            )
            if created:
                ctx.tasks_created += 1
        elif kind == "approval":
            action = step.get("action")
            step_n = step.get("step")
            label = f"approval ({action})" if step_n is None else f"approval ({action}, step {step_n})"
            ctx.dead_ends.append(f"{label}: not yet governed")
        else:
            ctx.dead_ends.append(f"{kind}: unknown step type")

        await drain_instance_tasks(
            conn,
            org=ctx.org,
            org_id=ctx.org_id,
            instance_id=inst,
            packs_dir=ctx.packs_dir,
            after_progress=lambda: _track_state(conn, ctx),
            run_attempt=ctx.run_attempt,
            dead_ends=ctx.dead_ends,
        )
        await _track_state(conn, ctx)
        ctx.tasks_created = await _count_tasks(conn, inst)

    assert ctx.instance_id
    cur = await conn.execute("select state from work.instances where id = %s", (ctx.instance_id,))
    reached = str((await cur.fetchone())[0])
    return {
        "workflow": ctx.workflow_name,
        "reached": reached,
        "path": list(ctx.path or []),
        "tasks_created": ctx.tasks_created,
        "committed_effects": 0,
        "dead_ends": list(ctx.dead_ends or []),
        "model": "fake",
    }


def _default_seat_for_workflow(pack_root: Path, workflow_name: str) -> str:
    pack = load_pack(pack_root)
    for _suite_name, suite in (pack.objects.get("EvalSuite") or {}).items():
        spec = suite.spec
        if spec.workflow == workflow_name and spec.targets:
            return str(spec.targets[0])
    raise ValueError(f"no seat found for workflow {workflow_name!r}")


async def _ensure_seats(conn: AsyncConnection, org: OrgModel, org_id: str, pack_version_id: str) -> None:
    await insert_seats_for_published_pack(
        conn,
        org=org,
        org_id=org_id,
        pack_version_id=pack_version_id,
    )
    await conn.execute(
        "update registry.seats set state = 'ACTIVE' where org_id = %s and pack_version_id = %s",
        (org_id, pack_version_id),
    )


async def run_simulation(
    conn: AsyncConnection,
    org: OrgModel,
    *,
    org_id: str,
    pack_version_id: str,
    workflow_name: str,
    script_name: str,
    packs_dir: Path,
    run_attempt: AttemptRunner | None = None,
) -> dict[str, Any]:
    await conn.execute(
        "update registry.pack_versions set status = 'published' where id = %s",
        (pack_version_id,),
    )
    await _ensure_seats(conn, org, org_id, pack_version_id)
    pcur = await conn.execute(
        "select pack_name from registry.pack_versions where id = %s",
        (pack_version_id,),
    )
    pack_name = (await pcur.fetchone())[0]
    pack_root = registry_store.pack_root(packs_dir, pack_name)
    steps = _load_script(pack_root, script_name)
    ctx = _SimContext(
        org=org,
        org_id=org_id,
        packs_dir=packs_dir,
        pack_version_id=pack_version_id,
        workflow_name=workflow_name,
        run_attempt=run_attempt,
    )
    return await _run_script(conn, ctx, steps)


async def run_simulation_from_pack_dir(
    conn: AsyncConnection,
    org: OrgModel,
    *,
    org_id: str,
    pack_dir: Path,
    workflow_name: str,
    script_name: str,
    packs_dir: Path | None = None,
    run_attempt: AttemptRunner | None = None,
) -> dict[str, Any]:
    pack_dir = pack_dir.resolve()
    root_packs = packs_dir or pack_dir.parent
    pack = load_pack(pack_dir)
    name = pack.manifest.metadata.name if pack.manifest else pack_dir.name
    result = await registry_store.sync_pack(
        conn,
        org=org,
        packs_dir=root_packs,
        name=name,
        actor="simulate",
        source="simulate",
    )
    return await run_simulation(
        conn,
        org,
        org_id=org_id,
        pack_version_id=result.pack_version_id,
        workflow_name=workflow_name,
        script_name=script_name,
        packs_dir=root_packs,
        run_attempt=run_attempt,
    )


async def run_simulation_rolled_back(
    pool: AsyncConnectionPool,
    org: OrgModel,
    *,
    org_id: str,
    pack_version_id: str,
    workflow_name: str,
    script_name: str,
    packs_dir: Path,
    run_attempt: AttemptRunner | None = None,
) -> dict[str, Any]:
    async with pool.connection() as conn:
        try:
            async with conn.transaction():
                report = await run_simulation(
                    conn,
                    org,
                    org_id=org_id,
                    pack_version_id=pack_version_id,
                    workflow_name=workflow_name,
                    script_name=script_name,
                    packs_dir=packs_dir,
                    run_attempt=run_attempt,
                )
                raise SimulationRollback(report)
        except SimulationRollback as exc:
            return exc.report


async def run_simulation_cli_rolled_back(
    pool: AsyncConnectionPool,
    org: OrgModel,
    *,
    org_id: str,
    pack_dir: Path,
    workflow_name: str,
    script_name: str,
    run_attempt: AttemptRunner | None = None,
) -> dict[str, Any]:
    async with pool.connection() as conn:
        try:
            async with conn.transaction():
                report = await run_simulation_from_pack_dir(
                    conn,
                    org,
                    org_id=org_id,
                    pack_dir=pack_dir,
                    workflow_name=workflow_name,
                    script_name=script_name,
                    run_attempt=run_attempt,
                )
                raise SimulationRollback(report)
        except SimulationRollback as exc:
            return exc.report
