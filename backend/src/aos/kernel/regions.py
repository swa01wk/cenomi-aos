"""Parallel region join guards, re-run and started_with (M2-BE-02)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from aos.registry.expressions import calls, evaluate
from aos.registry.kinds import TaskTemplate, WorkflowDefinition

from . import contracts, ids, workflow
from . import tasks as task_ops

if TYPE_CHECKING:
    from .org import OrgModel


def join_states(definition: WorkflowDefinition) -> set[str]:
    return {r.join_at for r in definition.spec.parallel}


def is_join_state(definition: WorkflowDefinition, state: str) -> bool:
    return state in join_states(definition)


def same_attributes(join_guard: str | None) -> list[str]:
    if not join_guard:
        return []
    out: list[str] = []
    for c in calls(join_guard):
        if c.function.split(".")[-1] != "same" or not c.argument:
            continue
        if c.argument not in out:
            out.append(c.argument)
    return out


def artifact_type_for_attr(definition: WorkflowDefinition, attr_name: str) -> str | None:
    for dname, dec in definition.spec.decisions.items():
        setter = dec.sets.get(attr_name)
        if setter != "artifact_version":
            continue
        view = definition.spec.states.get(dec.state)
        if view is not None and view.view:
            return view.view
    return None


def region_guard_holds(
    join_guard: str | None,
    attributes: dict[str, Any],
    started_with: dict[str, Any],
) -> bool:
    if not join_guard:
        return True
    scope: dict[str, dict[str, Any]] = {
        "attr": dict(attributes),
        "workflow": {"started_with": dict(started_with)},
    }
    return evaluate(join_guard, scope)


async def latest_artifact_version(
    conn: AsyncConnection, instance_id: str, artifact_type: str
) -> int | None:
    cur = await conn.execute(
        "select latest_version from work.artifacts"
        " where instance_id = %s and artifact_type = %s and key = ''"
        " order by latest_version desc limit 1",
        (instance_id, artifact_type),
    )
    row = await cur.fetchone()
    if row is None or int(row[0]) < 1:
        return None
    return int(row[0])


async def is_latest_region_task(
    conn: AsyncConnection, *, instance_id: str, region: str, task_id: str
) -> bool:
    """True when task_id is the region's current Task (work.regions.current_task).

    The kernel sets current_task whenever it creates a region's Task. A region row without one (written by hand,
    e.g. a test fixture) falls back to the newest Task by created_at; don't rely on that for Tasks created in one
    transaction, since now() is the transaction's start time and they tie.
    """
    cur = await conn.execute(
        "select current_task from work.regions where instance_id = %s and name = %s",
        (instance_id, region),
    )
    row = await cur.fetchone()
    if row is None:
        return False
    if row[0] is not None:
        return str(row[0]) == task_id
    cur = await conn.execute(
        "select id from work.tasks where instance_id = %s and region = %s and superseded_by is null"
        " order by created_at desc, id desc limit 1",
        (instance_id, region),
    )
    latest = await cur.fetchone()
    return latest is not None and str(latest[0]) == task_id


async def join_ready(
    conn: AsyncConnection,
    instance_id: str,
    state: str,
    definition: WorkflowDefinition,
    attributes: dict[str, Any],
) -> bool:
    required = [r for r in definition.spec.parallel if r.join_at == state]
    if not required:
        return True
    for spec in required:
        cur = await conn.execute(
            "select state, join_guard, started_with from work.regions"
            " where instance_id = %s and name = %s",
            (instance_id, spec.region),
        )
        row = await cur.fetchone()
        if row is None:
            return False
        rstate, join_guard, sw_raw = row[0], row[1], row[2]
        if rstate not in ("done", "joined"):
            return False
        started_with = sw_raw if isinstance(sw_raw, dict) else json.loads(sw_raw or "{}")
        if not region_guard_holds(join_guard, attributes, started_with):
            return False
    return True


async def mark_regions_joined(
    conn: AsyncConnection,
    instance_id: str,
    join_state: str,
    *,
    at: Any,
) -> None:
    await conn.execute(
        "update work.regions set state = 'joined', joined_at = %s"
        " where instance_id = %s and join_at = %s and state = 'done'",
        (at, instance_id, join_state),
    )


async def create_region_task(
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
    tpl: TaskTemplate,
    region_name: str,
    participants: list[tuple[str, str]],
    org: "OrgModel | None" = None,
) -> str:
    if tpl.on_behalf_of is None:
        raise ValueError(f"template {tpl.template!r} is missing on_behalf_of")
    role = tpl.on_behalf_of
    person_id = next((p for r, p in participants if r == role), None)
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
        region=region_name,
    )
    await conn.execute(
        "update work.regions set current_task = %s where instance_id = %s and name = %s",
        (task_id, instance_id, region_name),
    )
    return task_id


async def rerun_stale_regions(
    conn: AsyncConnection,
    instance_id: str,
    join_state: str,
    definition: WorkflowDefinition,
    attributes: dict[str, Any],
    *,
    packs_dir: Path,
    org_id: str,
    seat_name: str,
    seat_version: int,
    workflow_name: str,
    pack_name: str,
    pack_version: int,
    pack_digest: str,
    defs: dict[str, dict[str, dict]],
    seat_doc: dict[str, Any],
    seat_limits: dict[str, Any],
    participants: list[tuple[str, str]],
    org: "OrgModel | None" = None,
) -> list[str]:
    """Re-start regions that finished on stale inputs. Returns new task ids."""
    new_tasks: list[str] = []
    for spec in definition.spec.parallel:
        if spec.join_at != join_state:
            continue
        cur = await conn.execute(
            "select state, join_guard, started_with from work.regions"
            " where instance_id = %s and name = %s for update",
            (instance_id, spec.region),
        )
        row = await cur.fetchone()
        if row is None:
            continue
        rstate, join_guard, sw_raw = row[0], row[1], row[2]
        if rstate == "joined":
            continue
        if rstate != "done":
            continue
        started_with = sw_raw if isinstance(sw_raw, dict) else json.loads(sw_raw or "{}")
        if region_guard_holds(join_guard, attributes, started_with):
            continue
        await conn.execute(
            "update work.regions set state = 'running', started_with = '{}'::jsonb"
            " where instance_id = %s and name = %s",
            (instance_id, spec.region),
        )
        tpl = TaskTemplate.model_validate(spec.start.model_dump(by_alias=True))
        task_id = await create_region_task(
            conn,
            packs_dir=packs_dir,
            org_id=org_id,
            instance_id=instance_id,
            seat_name=seat_name,
            seat_version=seat_version,
            workflow_name=workflow_name,
            pack_name=pack_name,
            pack_version=pack_version,
            pack_digest=pack_digest,
            defs=defs,
            seat_doc=seat_doc,
            seat_limits=seat_limits,
            tpl=tpl,
            region_name=spec.region,
            participants=participants,
            org=org,
        )
        new_tasks.append(task_id)
    return new_tasks


async def record_started_with_on_admit(conn: AsyncConnection, task_id: str) -> None:
    cur = await conn.execute(
        "select instance_id, region from work.tasks where id = %s",
        (task_id,),
    )
    row = await cur.fetchone()
    if row is None or not row[1]:
        return
    instance_id, region_name = str(row[0]), str(row[1])

    # Lock the region row first (re-runs lock it too), then check this is still the region's latest Task.
    rcur = await conn.execute(
        "select join_guard, started_with from work.regions"
        " where instance_id = %s and name = %s for update",
        (instance_id, region_name),
    )
    rrow = await rcur.fetchone()
    if rrow is None:
        return
    if not await is_latest_region_task(
        conn, instance_id=instance_id, region=region_name, task_id=task_id
    ):
        return
    join_guard, sw_raw = rrow[0], rrow[1]
    attrs_in_guard = same_attributes(join_guard)
    if not attrs_in_guard:
        return

    icur = await conn.execute(
        "select workflow, pack_version_id from work.instances where id = %s",
        (instance_id,),
    )
    irow = await icur.fetchone()
    if irow is None:
        return
    workflow_name, pack_version_id = irow[0], str(irow[1])
    wcur = await conn.execute(
        "select spec from registry.definitions where pack_version_id = %s"
        " and kind = 'WorkflowDefinition' and name = %s",
        (pack_version_id, workflow_name),
    )
    wrow = await wcur.fetchone()
    if wrow is None:
        return
    wdoc = wrow[0] if isinstance(wrow[0], dict) else json.loads(wrow[0])
    definition = WorkflowDefinition.model_validate(wdoc)

    started_with = sw_raw if isinstance(sw_raw, dict) else json.loads(sw_raw or "{}")
    updated = dict(started_with)
    for attr_name in attrs_in_guard:
        art_type = artifact_type_for_attr(definition, attr_name)
        if art_type is None:
            continue
        ver = await latest_artifact_version(conn, instance_id, art_type)
        if ver is not None:
            updated[attr_name] = ver

    await conn.execute(
        "update work.regions set started_with = %s where instance_id = %s and name = %s",
        (Jsonb(updated), instance_id, region_name),
    )
