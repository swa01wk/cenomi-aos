"""Kernel-opened decisions and decidePending (M2-BE-04)."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from aos.registry.kinds import ArtifactType, WorkflowDecisionSpec, WorkflowDefinition

from . import audit_store, clock, ids, workflow
from .supplier_list_rows import supplier_list_has_real_rows
from .contracts import _canonical_json
from .org import OrgModel

_AT_LEAST = re.compile(r">=\s*(\d+)")


class DecisionError(Exception):
    def __init__(self, code: str, status: int, title: str, detail: str = "", **extra: Any) -> None:
        self.code = code
        self.status = status
        self.title = title
        self.detail = detail
        self.extra = extra
        super().__init__(title)


def _decision_request_hash(pending_id: str, body: dict[str, Any]) -> str:
    payload = {
        "pending_id": pending_id,
        "value": body.get("value"),
        "artifact_version": body.get("artifact_version"),
        "selection": body.get("selection"),
        "expected_version": body.get("expected_version"),
        "note": body.get("note"),
    }
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _decision_name_from_event(event: str) -> str:
    if not event.startswith("decision."):
        raise DecisionError("internal", 500, "Invalid pending event", f"Expected decision.*, got {event!r}.")
    return event.removeprefix("decision.")


async def _load_workflow(
    conn: AsyncConnection, instance_id: str
) -> tuple[str, str, WorkflowDefinition, dict[str, dict[str, dict]]]:
    cur = await conn.execute(
        "select org_id, workflow, pack_version_id from work.instances where id = %s",
        (instance_id,),
    )
    row = await cur.fetchone()
    if row is None:
        raise DecisionError("not_found", 404, "Job not found", f"No instance {instance_id!r}.")
    org_id, workflow_name, pack_version_id = row[0], row[1], str(row[2])
    cur = await conn.execute(
        "select spec from registry.definitions where pack_version_id = %s and kind = 'WorkflowDefinition'"
        " and name = %s",
        (pack_version_id, workflow_name),
    )
    wrow = await cur.fetchone()
    if wrow is None:
        raise DecisionError("internal", 500, "Workflow missing", "Pinned workflow definition not found.")
    wdoc = wrow[0] if isinstance(wrow[0], dict) else json.loads(wrow[0])
    definition = WorkflowDefinition.model_validate(wdoc)
    defs = await workflow._load_definitions(conn, pack_version_id)
    return org_id, workflow_name, definition, defs


async def _has_completed_task(conn: AsyncConnection, instance_id: str, template: str) -> bool:
    cur = await conn.execute(
        "select 1 from work.tasks"
        " where instance_id = %s and template = %s and state = 'COMPLETED'"
        " limit 1",
        (instance_id, template),
    )
    return (await cur.fetchone()) is not None


async def _state_tasks_complete(
    conn: AsyncConnection, instance_id: str, templates: list[str]
) -> bool:
    if not templates:
        return True
    for tpl in templates:
        if not await _has_completed_task(conn, instance_id, tpl):
            return False
    return True


async def pending_for_viewer(
    conn: AsyncConnection,
    instance_id: str,
    person_id: str,
    viewer_roles: list[str],
) -> list[dict[str, Any]]:
    """Open pending items visible to the caller (PendingItem shape)."""
    cur = await conn.execute(
        "select id, instance_id, kind, event, title, detail, for_role, for_person_id,"
        " options, artifact_ref, approval_id, due_at, status, created_at"
        " from work.pending_items where instance_id = %s and status = 'open'"
        " order by created_at",
        (instance_id,),
    )
    out: list[dict[str, Any]] = []
    for row in await cur.fetchall():
        (
            pid,
            inst_id,
            kind,
            event,
            title,
            detail,
            for_role,
            for_person,
            options,
            artifact_ref,
            approval_id,
            due_at,
            status,
            created_at,
        ) = row
        if for_person != person_id and for_role not in viewer_roles:
            continue
        options_doc = options if isinstance(options, list) else json.loads(options or "[]")
        art: dict[str, Any] | None
        if artifact_ref is None:
            art = None
        elif isinstance(artifact_ref, dict):
            art = dict(artifact_ref)
        else:
            art = dict(json.loads(artifact_ref))
        select_min = art.pop("select_min", None) if art is not None else None
        created: datetime | str = created_at
        item: dict[str, Any] = {
            "pending_id": pid,
            "instance_id": inst_id,
            "kind": kind,
            "event": event,
            "title": title,
            "detail": detail or "",
            "for_role": for_role,
            "for_person_id": for_person,
            "options": options_doc,
            "artifact_ref": art,
            "approval_id": approval_id,
            "due_at": due_at.isoformat() if due_at is not None else None,
            "status": status,
            "created_at": created.isoformat() if hasattr(created, "isoformat") else str(created),
        }
        if isinstance(select_min, int) and select_min >= 1:
            item["select_min"] = select_min
        out.append(item)
    return out


async def _latest_view_artifact(
    conn: AsyncConnection, instance_id: str, view_type: str
) -> tuple[str, int, str] | None:
    cur = await conn.execute(
        "select id, latest_version from work.artifacts"
        " where instance_id = %s and artifact_type = %s and key = ''"
        " order by latest_version desc limit 1",
        (instance_id, view_type),
    )
    row = await cur.fetchone()
    if row is None or int(row[1]) < 1:
        return None
    aid, ver = row[0], int(row[1])
    vcur = await conn.execute(
        "select content_hash from work.artifact_versions where artifact_id = %s and version = %s",
        (aid, ver),
    )
    vrow = await vcur.fetchone()
    if vrow is None:
        return None
    return aid, ver, str(vrow[0])


async def heal_missing_discovery_lookup(
    conn: AsyncConnection,
    instance_id: str,
    definition: WorkflowDefinition,
    *,
    org: OrgModel,
    packs_dir: Path,
) -> bool:
    """Brief confirmed but supplier search never started (e.g. category empty on an older pack pin)."""
    parallel = next((p for p in definition.spec.parallel if p.region == "discovery"), None)
    if parallel is None:
        return False
    cur = await conn.execute("select state from work.instances where id = %s", (instance_id,))
    row = await cur.fetchone()
    if row is None or str(row[0]) not in ("intake", "shortlisting"):
        return False
    rcur = await conn.execute(
        "select 1 from work.regions where instance_id = %s and name = 'discovery'",
        (instance_id,),
    )
    if await rcur.fetchone() is not None:
        return False
    bound = await _latest_view_artifact(conn, instance_id, "brief")
    if bound is None:
        return False
    aid, ver, _ = bound
    vcur = await conn.execute(
        "select content from work.artifact_versions where artifact_id = %s and version = %s",
        (aid, ver),
    )
    vrow = await vcur.fetchone()
    if vrow is None:
        return False
    content = vrow[0] if isinstance(vrow[0], dict) else json.loads(vrow[0])
    from .events import ensure_parallel_region_started, evaluate_artifact_triggers

    await evaluate_artifact_triggers(
        conn,
        org,
        instance_id,
        artifact_type="brief",
        content=content,
        packs_dir=packs_dir,
    )
    rcur = await conn.execute(
        "select 1 from work.regions where instance_id = %s and name = 'discovery'",
        (instance_id,),
    )
    if await rcur.fetchone() is not None:
        return True
    region_on = parallel.on if parallel.on.startswith("event.") else f"event.{parallel.on}"
    return await ensure_parallel_region_started(
        conn, org, instance_id, region_on=region_on, packs_dir=packs_dir
    )


def _infer_brief_category_id(content: dict[str, Any]) -> str:
    blob = f"{content.get('title') or ''} {content.get('specification') or ''} {content.get('notes') or ''}".lower()
    if any(
        k in blob
        for k in (
            "website",
            "web portal",
            "web service",
            "web redesign",
            "marketing website",
            "rest api",
            " bilingual",
            "cms",
            "ux/ui",
            "software development",
            "custom software",
            "web/api",
            " rfp",
            "formal rfp",
            "integrator",
        )
    ):
        return "CAT-IT-DEV"
    if any(k in blob for k in ("macbook", "laptop", "notebook", "ipad", "imac", "iphone", "phone")):
        return "CAT-IT-EUD"
    if any(k in blob for k in ("janitorial", "cleaning", " mop", "floor scrub")):
        return "CAT-JAN-EQ"
    return "CAT-IT-EUD"


async def _ensure_brief_category_for_lookup(
    conn: AsyncConnection,
    instance_id: str,
    defs: dict[str, dict[str, dict]],
) -> bool:
    bound = await _latest_view_artifact(conn, instance_id, "brief")
    if bound is None:
        return False
    aid, ver, _ = bound
    vcur = await conn.execute(
        "select content from work.artifact_versions where artifact_id = %s and version = %s",
        (aid, ver),
    )
    vrow = await vcur.fetchone()
    if vrow is None:
        return False
    content = dict(vrow[0] if isinstance(vrow[0], dict) else json.loads(vrow[0]))
    inferred = _infer_brief_category_id(content)
    current = content.get("category")
    current_s = current.strip() if isinstance(current, str) else ""
    if current_s == inferred:
        return False
    from .artifacts import parse_artifact_type, validate_artifact_content

    content["category"] = inferred
    at = parse_artifact_type(defs, "brief")
    if validate_artifact_content(at.spec, content, partial=False):
        return False
    new_ver = ver + 1
    content_hash = hashlib.sha256(_canonical_json(content)).hexdigest()
    rcur = await conn.execute(
        "select person_id from work.participants where instance_id = %s and role = 'requester' limit 1",
        (instance_id,),
    )
    rrow = await rcur.fetchone()
    actor = str(rrow[0]) if rrow else "requester"
    await conn.execute(
        "insert into work.artifact_versions ("
        " artifact_id, version, content, content_hash, produced_by_kind, produced_by, inputs, sources"
        ") values (%s, %s, %s, %s, 'person', %s, '[]'::jsonb, '[]'::jsonb)",
        (aid, new_ver, Jsonb(content), content_hash, actor),
    )
    await conn.execute(
        "update work.artifacts set latest_version = %s, status = 'draft' where id = %s",
        (new_ver, aid),
    )
    return True


async def heal_empty_supplier_list(
    conn: AsyncConnection,
    instance_id: str,
    definition: WorkflowDefinition,
    *,
    org: OrgModel,
    packs_dir: Path,
) -> bool:
    """Ranked list saved with zero rows — patch brief category if needed and rerun supplier_lookup once."""
    parallel = next((p for p in definition.spec.parallel if p.region == "discovery"), None)
    if parallel is None:
        return False
    cur = await conn.execute(
        "select state, attributes from work.instances where id = %s",
        (instance_id,),
    )
    row = await cur.fetchone()
    if row is None or str(row[0]) != "shortlisting":
        return False
    attrs = row[1] if isinstance(row[1], dict) else json.loads(row[1] or "{}")
    lcur = await conn.execute(
        "select v.content from work.artifacts a"
        " join work.artifact_versions v on v.artifact_id = a.id and v.version = a.latest_version"
        " where a.instance_id = %s and a.artifact_type = 'supplier_list' and coalesce(a.key, '') = ''"
        " limit 1",
        (instance_id,),
    )
    lrow = await lcur.fetchone()
    if lrow is None:
        return False
    list_content = lrow[0] if isinstance(lrow[0], dict) else json.loads(lrow[0])
    if supplier_list_has_real_rows(list_content if isinstance(list_content, dict) else {}):
        return False
    tcur = await conn.execute(
        "select state from work.tasks where instance_id = %s and template = 'supplier_lookup'"
        " order by created_at desc limit 1",
        (instance_id,),
    )
    trow = await tcur.fetchone()
    if trow is None or str(trow[0]) not in (
        "COMPLETED",
        "FAILED",
        "EXCEPTION",
        "WAITING_INPUT",
        "RUNNING",
        "READY",
        "CREATED",
    ):
        return False
    reruns = int(attrs.get("discovery_empty_rerun") or 0)
    if reruns >= 2:
        return False
    org_id, workflow_name, _, defs = await _load_workflow(conn, instance_id)
    await _ensure_brief_category_for_lookup(conn, instance_id, defs)
    inst_cur = await conn.execute(
        "select seat, seat_version, pack_version_id from work.instances where id = %s",
        (instance_id,),
    )
    inst = await inst_cur.fetchone()
    if inst is None:
        return False
    seat_name, seat_version, pack_version_id = inst[0], int(inst[1]), str(inst[2])
    pack_cur = await conn.execute(
        "select pack_name, version, digest from registry.pack_versions where id = %s",
        (pack_version_id,),
    )
    pack_row = await pack_cur.fetchone()
    if pack_row is None:
        return False
    pack_name, pack_ver, pack_digest = pack_row[0], int(pack_row[1]), pack_row[2]
    seat_doc = defs.get("Seat", {}).get(seat_name) or {}
    seat_limits = (seat_doc.get("spec") or {}).get("limits") or {}
    participants = await workflow._participants(conn, instance_id)
    from aos.registry.kinds import TaskTemplate

    from . import regions as region_ops

    await conn.execute(
        "update work.tasks set state = 'CANCELLED', updated_at = now()"
        " where instance_id = %s and template = 'supplier_lookup' and region = 'discovery'"
        " and state not in ('COMPLETED', 'CANCELLED')",
        (instance_id,),
    )
    brief_bound = await _latest_view_artifact(conn, instance_id, "brief")
    started_with = Jsonb({"brief_version": int(brief_bound[1]) if brief_bound else 1})
    await conn.execute(
        "update work.regions set state = 'running', started_with = %s"
        " where instance_id = %s and name = 'discovery'",
        (started_with, instance_id),
    )
    tpl = TaskTemplate.model_validate(parallel.start.model_dump(by_alias=True))
    await region_ops.create_region_task(
        conn,
        packs_dir=packs_dir,
        org_id=org_id,
        instance_id=instance_id,
        seat_name=seat_name,
        seat_version=seat_version,
        workflow_name=workflow_name,
        pack_name=pack_name,
        pack_version=pack_ver,
        pack_digest=pack_digest,
        defs=defs,
        seat_doc=seat_doc,
        seat_limits=seat_limits,
        tpl=tpl,
        region_name=parallel.region,
        participants=participants,
        org=org,
    )
    attrs = dict(attrs)
    attrs["discovery_empty_rerun"] = reruns + 1
    await conn.execute(
        "update work.instances set attributes = %s where id = %s",
        (Jsonb(attrs), instance_id),
    )
    return True


async def heal_stuck_discovery_region_with_list(
    conn: AsyncConnection,
    instance_id: str,
    definition: WorkflowDefinition,
) -> bool:
    """Ranked supplier_list exists but discovery still running (duplicate lookups) — close join."""
    if not any(p.region == "discovery" and p.join_at == "shortlisting" for p in definition.spec.parallel):
        return False
    cur = await conn.execute("select state from work.instances where id = %s", (instance_id,))
    row = await cur.fetchone()
    if row is None or str(row[0]) != "shortlisting":
        return False
    vcur = await conn.execute(
        "select v.content from work.artifacts a"
        " join work.artifact_versions v on v.artifact_id = a.id and v.version = a.latest_version"
        " where a.instance_id = %s and a.artifact_type = 'supplier_list' and coalesce(a.key, '') = ''"
        " limit 1",
        (instance_id,),
    )
    vrow = await vcur.fetchone()
    if vrow is None:
        return False
    list_content = vrow[0] if isinstance(vrow[0], dict) else json.loads(vrow[0])
    if not supplier_list_has_real_rows(list_content if isinstance(list_content, dict) else {}):
        return False
    rcur = await conn.execute(
        "select state from work.regions where instance_id = %s and name = 'discovery'",
        (instance_id,),
    )
    rrow = await rcur.fetchone()
    if rrow is None or str(rrow[0]) not in ("running",):
        return False
    await conn.execute(
        "update work.tasks set state = 'CANCELLED', updated_at = now()"
        " where instance_id = %s and region = 'discovery'"
        " and state in ('CREATED', 'READY', 'RUNNING', 'VERIFYING', 'WAITING_INPUT', 'WAITING_APPROVAL')",
        (instance_id,),
    )
    await conn.execute(
        "update work.regions set state = 'done' where instance_id = %s and name = 'discovery' and state = 'running'",
        (instance_id,),
    )
    return True


async def heal_discovery_region_after_lookup(
    conn: AsyncConnection,
    instance_id: str,
    definition: WorkflowDefinition,
) -> bool:
    """If parallel lookup ended but the discovery region stayed running, close it so the join can proceed."""
    if not any(p.region == "discovery" and p.join_at == "shortlisting" for p in definition.spec.parallel):
        return False
    rcur = await conn.execute(
        "select state, started_with from work.regions where instance_id = %s and name = 'discovery'",
        (instance_id,),
    )
    rrow = await rcur.fetchone()
    if rrow is None or rrow[0] != "running":
        return False
    sw_raw = rrow[1]
    started_with = sw_raw if isinstance(sw_raw, dict) else json.loads(sw_raw or "{}")
    if not started_with:
        return False
    vcur = await conn.execute(
        "select v.content from work.artifacts a"
        " join work.artifact_versions v on v.artifact_id = a.id and v.version = a.latest_version"
        " where a.instance_id = %s and a.artifact_type = 'supplier_list' and coalesce(a.key, '') = ''"
        " limit 1",
        (instance_id,),
    )
    vrow = await vcur.fetchone()
    if vrow is None:
        return False
    list_content = vrow[0] if isinstance(vrow[0], dict) else json.loads(vrow[0])
    if not supplier_list_has_real_rows(list_content if isinstance(list_content, dict) else {}):
        return False
    tcur = await conn.execute(
        "select state from work.tasks where instance_id = %s and region = 'discovery'"
        " order by created_at desc limit 1",
        (instance_id,),
    )
    trow = await tcur.fetchone()
    if trow is None or trow[0] in ("RUNNING", "READY", "CREATED"):
        return False
    await conn.execute(
        "update work.regions set state = 'done' where instance_id = %s and name = 'discovery' and state = 'running'",
        (instance_id,),
    )
    return True


async def _last_turn_author_kind(conn: AsyncConnection, instance_id: str) -> str | None:
    cur = await conn.execute(
        "select author_kind from work.turns where instance_id = %s order by seq desc limit 1",
        (instance_id,),
    )
    row = await cur.fetchone()
    return str(row[0]) if row else None


async def _assist_task_state(conn: AsyncConnection, instance_id: str) -> str | None:
    cur = await conn.execute(
        "select state from work.tasks where instance_id = %s and kind = 'assist' limit 1",
        (instance_id,),
    )
    row = await cur.fetchone()
    return str(row[0]) if row else None


async def _void_open_brief_confirm(conn: AsyncConnection, instance_id: str, *, voided_by: str) -> int:
    cur = await conn.execute(
        "select id, for_person_id from work.pending_items"
        " where instance_id = %s and status = 'open' and event = 'decision.brief_confirmed'"
        " for update",
        (instance_id,),
    )
    rows = await cur.fetchall()
    if not rows:
        return 0
    ts = clock.now()
    for pending_id, for_person in rows:
        await conn.execute(
            "update work.pending_items set status = 'voided', resolved_at = %s, resolved_by = %s where id = %s",
            (ts, voided_by, pending_id),
        )
        await _emit_pending_resolved(
            conn,
            instance_id=instance_id,
            person_id=str(for_person),
            pending_id=str(pending_id),
            outcome="voided",
            by=voided_by,
        )
    return len(rows)


async def intake_ready_for_confirm(
    conn: AsyncConnection,
    instance_id: str,
    defs: dict[str, dict[str, dict]],
) -> bool:
    """Request intake finished and the brief passes full schema validation."""
    cur = await conn.execute("select state from work.instances where id = %s", (instance_id,))
    row = await cur.fetchone()
    if row is None or str(row[0]) != "intake":
        return False
    intake_done = await _has_completed_task(conn, instance_id, "request_intake") or await _has_completed_task(
        conn, instance_id, "rfp_intake"
    )
    if not intake_done:
        return False
    bound = await _latest_view_artifact(conn, instance_id, "brief")
    if bound is None:
        return False
    aid, ver, _ = bound
    vcur = await conn.execute(
        "select content from work.artifact_versions where artifact_id = %s and version = %s",
        (aid, ver),
    )
    vrow = await vcur.fetchone()
    if vrow is None:
        return False
    content = vrow[0] if isinstance(vrow[0], dict) else json.loads(vrow[0])
    from .artifacts import parse_artifact_type, validate_artifact_content

    at = parse_artifact_type(defs, "brief")
    if validate_artifact_content(at.spec, content, partial=False):
        return False
    return True


async def reconcile_brief_confirm_pending(
    conn: AsyncConnection,
    instance_id: str,
    defs: dict[str, dict[str, dict]],
) -> bool:
    """Drop a brief confirm card that opened while the specialist still owes the requester a reply."""
    cur = await conn.execute("select state from work.instances where id = %s", (instance_id,))
    row = await cur.fetchone()
    if row is None or str(row[0]) != "intake":
        return False
    if await intake_ready_for_confirm(conn, instance_id, defs):
        return False
    open_cur = await conn.execute(
        "select 1 from work.pending_items"
        " where instance_id = %s and status = 'open' and event = 'decision.brief_confirmed' limit 1",
        (instance_id,),
    )
    if await open_cur.fetchone() is None:
        return False
    assist = await _assist_task_state(conn, instance_id)
    if assist in ("RUNNING", "VERIFYING", "READY", "CREATED"):
        return (await _void_open_brief_confirm(conn, instance_id, voided_by="kernel")) > 0
    if await _last_turn_author_kind(conn, instance_id) != "person":
        return (await _void_open_brief_confirm(conn, instance_id, voided_by="kernel")) > 0
    return False


async def _may_open_brief_confirmed(
    conn: AsyncConnection,
    instance_id: str,
    defs: dict[str, dict[str, dict]],
) -> bool:
    if await intake_ready_for_confirm(conn, instance_id, defs):
        return True
    assist = await _assist_task_state(conn, instance_id)
    if assist in ("RUNNING", "VERIFYING", "READY", "CREATED"):
        return False
    return await _last_turn_author_kind(conn, instance_id) == "person"


async def heal_rfq_draft_after_saved_emails(
    conn: AsyncConnection,
    instance_id: str,
    *,
    org: OrgModel,
    packs_dir: Path,
    definition: WorkflowDefinition,
    attributes: dict[str, Any],
) -> bool:
    """RFQ emails saved but the worker hit attempt step budget — close rfq_draft and advance."""
    cur = await conn.execute("select state, status from work.instances where id = %s", (instance_id,))
    row = await cur.fetchone()
    if row is None or str(row[0]) != "rfq_drafting" or str(row[1]) != "running":
        return False
    need = max(1, int(attributes.get("shortlist_count") or 3))
    ecur = await conn.execute(
        "select count(*) from work.artifacts"
        " where instance_id = %s and artifact_type = 'rfq_email' and latest_version >= 1",
        (instance_id,),
    )
    if int((await ecur.fetchone())[0]) < need:
        return False
    tcur = await conn.execute(
        "select t.id, t.state from work.tasks t"
        " where t.instance_id = %s and t.template = 'rfq_draft'"
        " order by t.created_at desc",
        (instance_id,),
    )
    tasks = await tcur.fetchall()
    if not tasks:
        return False
    if any(str(s) == "COMPLETED" for _, s in tasks):
        return False
    if any(str(s) in ("RUNNING", "READY", "CREATED", "VERIFYING") for _, s in tasks):
        return False
    if not any(str(s) == "EXCEPTION" for _, s in tasks):
        return False
    fail_cur = await conn.execute(
        "select 1 from work.attempts a"
        " join work.tasks t on t.id = a.task_id"
        " where t.instance_id = %s and t.template = 'rfq_draft' and a.failure_class = 'budget_exhausted'"
        " limit 1",
        (instance_id,),
    )
    if await fail_cur.fetchone() is None:
        return False

    complete_id = str(tasks[0][0])
    for tid, state in tasks[1:]:
        if str(state) not in ("EXCEPTION", "CANCELLED"):
            await conn.execute(
                "update work.tasks set state = 'CANCELLED', updated_at = now() where id = %s",
                (str(tid),),
            )
    await conn.execute(
        "update work.tasks set state = 'COMPLETED', updated_at = now() where id = %s",
        (complete_id,),
    )
    from .task_retry import void_open_task_retry

    retry_cur = await conn.execute(
        "select p.id, p.for_person_id from work.pending_items p"
        " join work.tasks t on t.id = p.task_id"
        " where p.instance_id = %s and p.status = 'open' and p.event = 'task.retry'"
        " and t.template = 'rfq_draft'",
        (instance_id,),
    )
    for pending_id, for_person in await retry_cur.fetchall():
        await void_open_task_retry(
            conn,
            instance_id=instance_id,
            pending_id=str(pending_id),
            for_person_id=str(for_person),
            voided_by="kernel",
        )
    from . import events as workflow_events

    await workflow_events.on_workflow_task_completed(
        conn, org, instance_id=instance_id, task_id=complete_id, packs_dir=packs_dir
    )
    return True


async def heal_intake_when_brief_valid(
    conn: AsyncConnection,
    instance_id: str,
    *,
    org: OrgModel,
    packs_dir: Path,
    definition: WorkflowDefinition,
    defs: dict[str, dict[str, dict]],
) -> bool:
    """When intake tasks failed (often budget) but the brief already passes full validation, complete intake."""
    st_cur = await conn.execute("select state from work.instances where id = %s", (instance_id,))
    st_row = await st_cur.fetchone()
    if st_row is None or str(st_row[0]) != "intake":
        return False
    intake_spec = definition.spec.states.get("intake")
    if intake_spec is None or not intake_spec.tasks:
        return False
    template = next(
        (t.template for t in intake_spec.tasks if t.template in ("request_intake", "rfp_intake")),
        None,
    )
    if template is None:
        return False
    if await _has_completed_task(conn, instance_id, template):
        return False
    bound = await _latest_view_artifact(conn, instance_id, "brief")
    if bound is None:
        return False
    aid, ver, _ = bound
    vcur = await conn.execute(
        "select content from work.artifact_versions where artifact_id = %s and version = %s",
        (aid, ver),
    )
    vrow = await vcur.fetchone()
    if vrow is None:
        return False
    content = vrow[0] if isinstance(vrow[0], dict) else json.loads(vrow[0])
    from .artifacts import parse_artifact_type, validate_artifact_content

    at = parse_artifact_type(defs, "brief")
    if validate_artifact_content(at.spec, content, partial=False):
        return False
    tcur = await conn.execute(
        "select t.id, t.state from work.tasks t"
        " where t.instance_id = %s and t.template = %s and t.region is null"
        " order by t.created_at desc",
        (instance_id, template),
    )
    tasks = await tcur.fetchall()
    if not tasks:
        return False
    if any(str(s) in ("RUNNING", "READY", "CREATED", "VERIFYING", "WAITING_INPUT") for _, s in tasks):
        return False
    if not any(str(s) == "EXCEPTION" for _, s in tasks):
        return False
    complete_id = str(tasks[0][0])
    for tid, state in tasks[1:]:
        if str(state) not in ("EXCEPTION", "CANCELLED"):
            await conn.execute(
                "update work.tasks set state = 'CANCELLED', updated_at = now() where id = %s",
                (str(tid),),
            )
    await conn.execute(
        "update work.tasks set state = 'COMPLETED', updated_at = now() where id = %s",
        (complete_id,),
    )
    from .task_retry import void_open_task_retry

    retry_cur = await conn.execute(
        "select p.id, p.for_person_id from work.pending_items p"
        " join work.tasks t on t.id = p.task_id"
        " where p.instance_id = %s and p.status = 'open' and p.event = 'task.retry'"
        " and t.template = %s",
        (instance_id, template),
    )
    for pending_id, for_person in await retry_cur.fetchall():
        await void_open_task_retry(
            conn,
            instance_id=instance_id,
            pending_id=str(pending_id),
            for_person_id=str(for_person),
            voided_by="kernel",
        )
    from . import events as workflow_events

    await workflow_events.on_workflow_task_completed(
        conn, org, instance_id=instance_id, task_id=complete_id, packs_dir=packs_dir
    )
    return True


async def heal_quote_comparison_after_quote(
    conn: AsyncConnection,
    instance_id: str,
    *,
    org: OrgModel,
    packs_dir: Path,
) -> bool:
    """Quote captured but comparison worker exhausted step budget — rank from saved quotes and advance."""
    cur = await conn.execute("select state, status from work.instances where id = %s", (instance_id,))
    row = await cur.fetchone()
    if row is None or str(row[0]) != "comparison" or str(row[1]) != "running":
        return False
    cmp_cur = await conn.execute(
        "select 1 from work.artifacts where instance_id = %s and artifact_type = 'comparison' limit 1",
        (instance_id,),
    )
    if await cmp_cur.fetchone() is not None:
        return False
    qcur = await conn.execute(
        "select v.content from work.artifacts a"
        " join work.artifact_versions v on v.artifact_id = a.id and v.version = a.latest_version"
        " where a.instance_id = %s and a.artifact_type = 'quote' and a.latest_version >= 1"
        " order by v.created_at",
        (instance_id,),
    )
    quote_rows: list[dict[str, Any]] = []
    for (raw,) in await qcur.fetchall():
        content = raw if isinstance(raw, dict) else json.loads(raw or "{}")
        supplier = str(content.get("supplier") or "").strip()
        unit = content.get("unit_price")
        total = content.get("total")
        lead = content.get("lead_time_days")
        if not supplier:
            continue
        if unit is None and total is None:
            continue
        if unit is None and total is not None:
            unit = total
        if total is None and unit is not None:
            total = unit
        if lead is None:
            lead = 0
        quote_rows.append(
            {
                "supplier": supplier,
                "unit_price": unit,
                "total": total,
                "lead_time_days": int(lead),
                "warranty_months": content.get("warranty_months"),
            }
        )
    if not quote_rows:
        return False
    tcur = await conn.execute(
        "select t.id, t.state from work.tasks t"
        " where t.instance_id = %s and t.template = 'quote_comparison' and t.region is null"
        " order by t.created_at desc",
        (instance_id,),
    )
    tasks = await tcur.fetchall()
    if not tasks:
        return False
    if any(str(s) == "COMPLETED" for _, s in tasks):
        return False
    if any(str(s) in ("RUNNING", "READY", "CREATED", "VERIFYING") for _, s in tasks):
        return False
    if not any(str(s) == "EXCEPTION" for _, s in tasks):
        return False
    fail_cur = await conn.execute(
        "select 1 from work.attempts a"
        " join work.tasks t on t.id = a.task_id"
        " where t.instance_id = %s and t.template = 'quote_comparison'"
        " and a.failure_class = 'budget_exhausted' limit 1",
        (instance_id,),
    )
    if await fail_cur.fetchone() is None:
        return False

    ranked = sorted(quote_rows, key=lambda r: (float(r["total"]), int(r["lead_time_days"])))
    rows: list[dict[str, Any]] = []
    for i, q in enumerate(ranked, start=1):
        score = round(100.0 - (i - 1) * 5.0, 2)
        row: dict[str, Any] = {
            "rank": i,
            "supplier": q["supplier"],
            "unit_price": q["unit_price"],
            "total": q["total"],
            "lead_time_days": q["lead_time_days"],
            "score": score,
        }
        if q.get("warranty_months") is not None:
            row["warranty_months"] = q["warranty_months"]
        rows.append(row)
    comparison_content = {"rows": rows}
    from . import participants as participant_ops

    buyer_id = await participant_ops.resolve_participant(
        conn, org, instance_id, "buyer", packs_dir=packs_dir
    )
    if buyer_id is None:
        return False
    artifact_id = ids.new_artifact_id()
    content_hash = hashlib.sha256(_canonical_json(comparison_content)).hexdigest()
    await conn.execute(
        "insert into work.artifacts (id, instance_id, artifact_type, key, name, status, latest_version)"
        " values (%s, %s, 'comparison', '', 'Comparison', 'draft', 1)",
        (artifact_id, instance_id),
    )
    await conn.execute(
        "insert into work.artifact_versions (artifact_id, version, content, content_hash, produced_by_kind,"
        " produced_by, inputs, sources) values (%s, 1, %s, %s, 'person', %s, '[]'::jsonb, '[]'::jsonb)",
        (artifact_id, Jsonb(comparison_content), content_hash, buyer_id),
    )

    complete_id = str(tasks[0][0])
    for tid, state in tasks[1:]:
        if str(state) not in ("EXCEPTION", "CANCELLED"):
            await conn.execute(
                "update work.tasks set state = 'CANCELLED', updated_at = now() where id = %s",
                (str(tid),),
            )
    await conn.execute(
        "update work.tasks set state = 'COMPLETED', updated_at = now() where id = %s",
        (complete_id,),
    )
    from .task_retry import void_open_task_retry

    retry_cur = await conn.execute(
        "select p.id, p.for_person_id from work.pending_items p"
        " join work.tasks t on t.id = p.task_id"
        " where p.instance_id = %s and p.status = 'open' and p.event = 'task.retry'"
        " and t.template = 'quote_comparison'",
        (instance_id,),
    )
    for pending_id, for_person in await retry_cur.fetchall():
        await void_open_task_retry(
            conn,
            instance_id=instance_id,
            pending_id=str(pending_id),
            for_person_id=str(for_person),
            voided_by="kernel",
        )
    from . import events as workflow_events

    await workflow_events.on_workflow_task_completed(
        conn, org, instance_id=instance_id, task_id=complete_id, packs_dir=packs_dir
    )
    return True


async def heal_po_create_after_budget_exhausted(
    conn: AsyncConnection,
    instance_id: str,
    *,
    org: OrgModel,
    packs_dir: Path,
) -> bool:
    """Demo reliability: auto-retry po_create when the worker exhausted its step budget."""
    cur = await conn.execute("select state, status from work.instances where id = %s", (instance_id,))
    row = await cur.fetchone()
    if row is None or str(row[0]) != "ordering" or str(row[1]) != "running":
        return False
    pcur = await conn.execute(
        "select 1 from work.artifacts a"
        " where a.instance_id = %s and a.artifact_type = 'po_payload' and a.latest_version >= 1 limit 1",
        (instance_id,),
    )
    if await pcur.fetchone() is not None:
        return False
    tcur = await conn.execute(
        "select t.id, t.state from work.tasks t"
        " where t.instance_id = %s and t.template = 'po_create' and t.region is null"
        " order by t.created_at desc",
        (instance_id,),
    )
    tasks = await tcur.fetchall()
    if not tasks or any(str(s) == "COMPLETED" for _, s in tasks):
        return False
    if any(str(s) in ("RUNNING", "READY", "CREATED", "VERIFYING") for _, s in tasks):
        return False
    if len(tasks) >= 4:
        return False
    failed_id = str(tasks[0][0])
    if str(tasks[0][1]) != "EXCEPTION":
        return False
    fail_cur = await conn.execute(
        "select 1 from work.attempts a"
        " where a.task_id = %s and a.failure_class = 'budget_exhausted' limit 1",
        (failed_id,),
    )
    if await fail_cur.fetchone() is None:
        return False

    inst_cur = await conn.execute(
        "select org_id, workflow, pack_version_id, seat, seat_version from work.instances where id = %s",
        (instance_id,),
    )
    inst = await inst_cur.fetchone()
    if inst is None:
        return False
    org_id, workflow_name, pack_version_id, seat_name, seat_version = inst
    wcur = await conn.execute(
        "select spec from registry.definitions where pack_version_id = %s and kind = 'WorkflowDefinition'"
        " and name = %s",
        (str(pack_version_id), workflow_name),
    )
    wrow = await wcur.fetchone()
    if wrow is None:
        return False
    definition = WorkflowDefinition.model_validate(
        wrow[0] if isinstance(wrow[0], dict) else json.loads(wrow[0])
    )
    from .task_retry import spawn_replacement_task, void_open_task_retry

    new_task_id = await spawn_replacement_task(
        conn,
        packs_dir=packs_dir,
        org=org,
        org_id=str(org_id),
        instance_id=instance_id,
        failed_task_id=failed_id,
        definition=definition,
        workflow_name=str(workflow_name),
        pack_version_id=str(pack_version_id),
        seat_name=str(seat_name),
        seat_version=int(seat_version),
    )
    await conn.execute(
        """
        update work.tasks set contract = jsonb_set(
          jsonb_set(jsonb_set(contract, '{budget,steps}', '24'),
          '{budget,actions}', '14'),
          '{budget,retries}', '3')
        where id = %s
        """,
        (new_task_id,),
    )
    retry_cur = await conn.execute(
        "select p.id, p.for_person_id from work.pending_items p"
        " join work.tasks t on t.id = p.task_id"
        " where p.instance_id = %s and p.status = 'open' and p.event = 'task.retry'"
        " and t.template = 'po_create'",
        (instance_id,),
    )
    for pending_id, for_person in await retry_cur.fetchall():
        await void_open_task_retry(
            conn,
            instance_id=instance_id,
            pending_id=str(pending_id),
            for_person_id=str(for_person),
            voided_by="kernel",
        )
    return True


async def heal_po_create_after_payload(
    conn: AsyncConnection,
    instance_id: str,
    *,
    org: OrgModel,
    packs_dir: Path,
) -> bool:
    """PO payload saved but po_create stalled (missing verifier, questions, or retry) — finish ordering."""
    cur = await conn.execute("select state, status from work.instances where id = %s", (instance_id,))
    row = await cur.fetchone()
    if row is None or str(row[0]) != "ordering" or str(row[1]) != "running":
        return False
    pcur = await conn.execute(
        "select v.content from work.artifacts a"
        " join work.artifact_versions v on v.artifact_id = a.id and v.version = a.latest_version"
        " where a.instance_id = %s and a.artifact_type = 'po_payload' and a.latest_version >= 1"
        " order by v.created_at desc limit 1",
        (instance_id,),
    )
    prow = await pcur.fetchone()
    if prow is None:
        return False
    payload = prow[0] if isinstance(prow[0], dict) else json.loads(prow[0] or "{}")
    lines = payload.get("lines")
    if not str(payload.get("supplier_id") or "").strip():
        return False
    if not isinstance(lines, list) or not lines:
        return False
    if payload.get("po_amount") is None:
        return False

    tcur = await conn.execute(
        "select t.id, t.state from work.tasks t"
        " where t.instance_id = %s and t.template = 'po_create' and t.region is null"
        " order by t.created_at desc",
        (instance_id,),
    )
    tasks = await tcur.fetchall()
    if not tasks or any(str(s) == "COMPLETED" for _, s in tasks):
        return False
    if any(str(s) in ("RUNNING", "READY", "CREATED", "VERIFYING") for _, s in tasks):
        return False
    stuck = ("EXCEPTION", "WAITING_INPUT", "CANCELLED")
    if not any(str(s) in stuck for _, s in tasks):
        return False

    complete_id = str(tasks[0][0])
    for tid, state in tasks[1:]:
        if str(state) not in stuck:
            await conn.execute(
                "update work.tasks set state = 'CANCELLED', updated_at = now() where id = %s",
                (str(tid),),
            )
    await conn.execute(
        "update work.tasks set state = 'COMPLETED', updated_at = now() where id = %s",
        (complete_id,),
    )
    from .task_retry import void_open_task_retry

    retry_cur = await conn.execute(
        "select p.id, p.for_person_id from work.pending_items p"
        " join work.tasks t on t.id = p.task_id"
        " where p.instance_id = %s and p.status = 'open' and p.event = 'task.retry'"
        " and t.template = 'po_create'",
        (instance_id,),
    )
    for pending_id, for_person in await retry_cur.fetchall():
        await void_open_task_retry(
            conn,
            instance_id=instance_id,
            pending_id=str(pending_id),
            for_person_id=str(for_person),
            voided_by="kernel",
        )
    from . import events as workflow_events

    await workflow_events.on_workflow_task_completed(
        conn, org, instance_id=instance_id, task_id=complete_id, packs_dir=packs_dir
    )
    return True


async def _rfq_send_receipt_keys(attributes: dict[str, Any]) -> set[str]:
    keys = attributes.get("rfq_sent_keys") or []
    return {str(k) for k in keys if k}


async def heal_rfq_send_after_receipts(
    conn: AsyncConnection,
    instance_id: str,
    *,
    org: OrgModel,
    packs_dir: Path,
    attributes: dict[str, Any],
) -> bool:
    """Outbound worker hit budget after sends were recorded — close rfq_send and advance."""
    cur = await conn.execute("select state, status from work.instances where id = %s", (instance_id,))
    row = await cur.fetchone()
    if row is None or str(row[0]) != "rfq_sending" or str(row[1]) != "running":
        return False
    need = max(1, int(attributes.get("shortlist_count") or 3))
    sent = await _rfq_send_receipt_keys(attributes)
    if len(sent) < need:
        return False
    ecur = await conn.execute(
        "select a.key from work.artifacts a"
        " where a.instance_id = %s and a.artifact_type = 'rfq_email' and a.latest_version >= 1",
        (instance_id,),
    )
    supplier_ids = [str(r[0]) for r in await ecur.fetchall() if r[0]]
    if len(supplier_ids) < need:
        return False
    for sid in supplier_ids[:need]:
        receipt = f"{instance_id}:rfq_send:{sid}"
        if receipt not in sent:
            return False
    tcur = await conn.execute(
        "select t.id, t.state from work.tasks t"
        " where t.instance_id = %s and t.template = 'rfq_send' and t.region is null"
        " order by t.created_at desc",
        (instance_id,),
    )
    tasks = await tcur.fetchall()
    if not tasks or any(str(s) == "COMPLETED" for _, s in tasks):
        return False
    if any(str(s) in ("RUNNING", "READY", "CREATED", "VERIFYING") for _, s in tasks):
        return False
    if not any(str(s) == "EXCEPTION" for _, s in tasks):
        return False
    fail_cur = await conn.execute(
        "select 1 from work.attempts a"
        " join work.tasks t on t.id = a.task_id"
        " where t.instance_id = %s and t.template = 'rfq_send' and a.failure_class = 'budget_exhausted'"
        " limit 1",
        (instance_id,),
    )
    if await fail_cur.fetchone() is None:
        return False
    complete_id = str(tasks[0][0])
    for tid, state in tasks[1:]:
        if str(state) not in ("EXCEPTION", "CANCELLED"):
            await conn.execute(
                "update work.tasks set state = 'CANCELLED', updated_at = now() where id = %s",
                (str(tid),),
            )
    await conn.execute(
        "update work.tasks set state = 'COMPLETED', updated_at = now() where id = %s",
        (complete_id,),
    )
    from .task_retry import void_open_task_retry

    retry_cur = await conn.execute(
        "select p.id, p.for_person_id from work.pending_items p"
        " join work.tasks t on t.id = p.task_id"
        " where p.instance_id = %s and p.status = 'open' and p.event = 'task.retry'"
        " and t.template = 'rfq_send'",
        (instance_id,),
    )
    for pending_id, for_person in await retry_cur.fetchall():
        await void_open_task_retry(
            conn,
            instance_id=instance_id,
            pending_id=str(pending_id),
            for_person_id=str(for_person),
            voided_by="kernel",
        )
    from . import events as workflow_events

    await workflow_events.on_workflow_task_completed(
        conn, org, instance_id=instance_id, task_id=complete_id, packs_dir=packs_dir
    )
    return True


async def heal_stale_outbound_send_retry(conn: AsyncConnection, instance_id: str) -> bool:
    """Work-panel send replaces a failed outbound-send task; drop a stale retry card."""
    cur = await conn.execute("select state from work.instances where id = %s", (instance_id,))
    row = await cur.fetchone()
    if row is None or not str(row[0]).endswith("_sending"):
        return False
    has_drafts = await conn.execute(
        "select 1 from work.artifacts a"
        " join registry.definitions d on d.name = a.artifact_type and d.kind = 'ArtifactType'"
        " where a.instance_id = %s"
        " and (d.spec::jsonb -> 'view' ->> 'type') = 'message_composer'"
        " limit 1",
        (instance_id,),
    )
    if await has_drafts.fetchone() is None:
        return False
    retry_cur = await conn.execute(
        "select p.id, p.for_person_id from work.pending_items p"
        " join work.tasks t on t.id = p.task_id"
        " where p.instance_id = %s and p.status = 'open' and p.event = 'task.retry'"
        " and t.region is null limit 1",
        (instance_id,),
    )
    retry = await retry_cur.fetchone()
    if retry is None:
        return False
    from .task_retry import void_open_task_retry

    await void_open_task_retry(
        conn,
        instance_id=instance_id,
        pending_id=str(retry[0]),
        for_person_id=str(retry[1]),
        voided_by="kernel",
    )
    return True


def _selection_minimum(definition: WorkflowDefinition, event: str) -> int:
    for tr in definition.spec.transitions:
        if event in tr.events and tr.guard:
            match = _AT_LEAST.search(tr.guard)
            if match:
                return int(match.group(1))
    return 1


def _pending_payload(
    *,
    pending_id: str,
    instance_id: str,
    event: str,
    title: str,
    for_role: str,
    for_person_id: str,
    artifact_ref: dict[str, Any] | None,
    created_at: datetime,
    detail: str = "",
    select_min: int | None = None,
) -> dict[str, Any]:
    options = [{"value": "confirm", "label": title}]
    public_ref = None
    if artifact_ref is not None:
        public_ref = {"artifact_id": artifact_ref.get("artifact_id"), "version": artifact_ref.get("version")}
    payload: dict[str, Any] = {
        "pending_id": pending_id,
        "instance_id": instance_id,
        "kind": "decision",
        "event": event,
        "title": title,
        "detail": detail,
        "for_role": for_role,
        "for_person_id": for_person_id,
        "options": options,
        "artifact_ref": public_ref,
        "approval_id": None,
        "due_at": None,
        "status": "open",
        "created_at": created_at.isoformat(),
    }
    if select_min is not None:
        payload["select_min"] = select_min
    return payload


async def _emit_pending_created(
    conn: AsyncConnection,
    *,
    instance_id: str,
    person_id: str,
    pending: dict[str, Any],
) -> None:
    from .outbox import OutboxRow, append_outbox_many

    at = pending["created_at"]
    rows = [
        OutboxRow(
            stream=ids.stream_user(person_id),
            event_type="pending.created",
            instance_id=instance_id,
            audience={"person_id": person_id},
            data={"instance_id": instance_id, "pending": pending},
        ),
        OutboxRow(
            stream=ids.stream_instance(instance_id),
            event_type="pending.created",
            instance_id=instance_id,
            audience={"person_id": person_id},
            data={"instance_id": instance_id, "pending": pending},
        ),
    ]
    await append_outbox_many(conn, rows)


async def _emit_pending_resolved(
    conn: AsyncConnection,
    *,
    instance_id: str,
    person_id: str,
    pending_id: str,
    outcome: str,
    by: str,
) -> None:
    from .outbox import OutboxRow, append_outbox_many

    data = {
        "instance_id": instance_id,
        "pending_id": pending_id,
        "outcome": outcome,
        "by": by,
    }
    await append_outbox_many(
        conn,
        [
            OutboxRow(
                stream=ids.stream_user(person_id),
                event_type="pending.resolved",
                instance_id=instance_id,
                audience={"person_id": person_id},
                data=data,
            ),
            OutboxRow(
                stream=ids.stream_instance(instance_id),
                event_type="pending.resolved",
                instance_id=instance_id,
                audience={"person_id": person_id},
                data=data,
            ),
        ],
    )


async def heal_shortlisting_join_brief_version(
    conn: AsyncConnection,
    instance_id: str,
    definition: WorkflowDefinition,
    attributes: dict[str, Any],
) -> bool:
    """Align discovery started_with with brief_version after a kernel brief patch (same() join guard)."""
    if not any(p.region == "discovery" and p.join_at == "shortlisting" for p in definition.spec.parallel):
        return False
    cur = await conn.execute("select state from work.instances where id = %s", (instance_id,))
    row = await cur.fetchone()
    if row is None or str(row[0]) != "shortlisting":
        return False
    from . import regions as region_ops

    if await region_ops.join_ready(conn, instance_id, "shortlisting", definition, attributes):
        return False
    rcur = await conn.execute(
        "select state, join_guard, started_with from work.regions where instance_id = %s and name = 'discovery'",
        (instance_id,),
    )
    rrow = await rcur.fetchone()
    if rrow is None or str(rrow[0]) not in ("done", "joined"):
        return False
    join_guard, sw_raw = rrow[1], rrow[2]
    started_with = sw_raw if isinstance(sw_raw, dict) else json.loads(sw_raw or "{}")
    if not region_ops.same_attributes(str(join_guard or "")):
        return False
    brief_ver = attributes.get("brief_version")
    if brief_ver is None:
        latest = await region_ops.latest_artifact_version(conn, instance_id, "brief")
        if latest is None:
            return False
        brief_ver = latest
    await conn.execute(
        "update work.regions set started_with = %s where instance_id = %s and name = 'discovery'",
        (Jsonb({"brief_version": int(brief_ver)}), instance_id),
    )
    return True


async def open_ready_decisions(
    conn: AsyncConnection,
    instance_id: str,
    *,
    org: OrgModel,
    packs_dir: Path,
) -> list[str]:
    """Open pending items for decisions whose preconditions hold. Idempotent per decision event."""
    cur = await conn.execute(
        "select state, status, attributes from work.instances where id = %s",
        (instance_id,),
    )
    row = await cur.fetchone()
    if row is None or row[1] != "running":
        return []
    state = row[0]
    attributes_raw = row[2]
    attributes = attributes_raw if isinstance(attributes_raw, dict) else json.loads(attributes_raw or "{}")
    _org_id, _wf_name, definition, defs = await _load_workflow(conn, instance_id)
    if str(state) in ("intake", "shortlisting"):
        await _ensure_brief_category_for_lookup(conn, instance_id, defs)
    await heal_missing_discovery_lookup(conn, instance_id, definition, org=org, packs_dir=packs_dir)
    await heal_empty_supplier_list(conn, instance_id, definition, org=org, packs_dir=packs_dir)
    await heal_stuck_discovery_region_with_list(conn, instance_id, definition)
    await heal_discovery_region_after_lookup(conn, instance_id, definition)
    await heal_shortlisting_join_brief_version(conn, instance_id, definition, attributes)
    await heal_stale_outbound_send_retry(conn, instance_id)
    await heal_rfq_draft_after_saved_emails(
        conn, instance_id, org=org, packs_dir=packs_dir, definition=definition, attributes=attributes
    )
    await heal_rfq_send_after_receipts(
        conn, instance_id, org=org, packs_dir=packs_dir, attributes=attributes
    )
    await heal_quote_comparison_after_quote(conn, instance_id, org=org, packs_dir=packs_dir)
    await heal_po_create_after_payload(conn, instance_id, org=org, packs_dir=packs_dir)
    await heal_po_create_after_budget_exhausted(conn, instance_id, org=org, packs_dir=packs_dir)
    await heal_intake_when_brief_valid(
        conn, instance_id, org=org, packs_dir=packs_dir, definition=definition, defs=defs
    )
    await reconcile_brief_confirm_pending(conn, instance_id, defs)
    starter_cur = await conn.execute(
        "select org_id, created_by from work.instances where id = %s",
        (instance_id,),
    )
    starter_row = await starter_cur.fetchone()
    org_id = str(starter_row[0]) if starter_row else ""
    job_starter = str(starter_row[1]) if starter_row and starter_row[1] else ""
    from . import regions as region_ops
    opened: list[str] = []
    ts = clock.now()
    for dname, dec in definition.spec.decisions.items():
        if dec.state != state:
            continue
        event = f"decision.{dname}"
        open_cur = await conn.execute(
            "select 1 from work.pending_items where instance_id = %s and event = %s and status = 'open' limit 1",
            (instance_id, event),
        )
        if await open_cur.fetchone() is not None:
            continue
        templates = [t.template for t in definition.spec.states[dec.state].tasks]
        if not await _state_tasks_complete(conn, instance_id, templates):
            continue
        if not await region_ops.join_ready(conn, instance_id, dec.state, definition, attributes):
            continue
        if event == "decision.brief_confirmed" and not await _may_open_brief_confirmed(
            conn, instance_id, defs
        ):
            continue
        from . import participants as participant_ops

        person_id = await participant_ops.resolve_participant(
            conn, org, instance_id, dec.for_, packs_dir=packs_dir
        )
        if person_id is None:
            continue
        view = definition.spec.states[dec.state].view
        artifact_ref: dict[str, Any] | None = None
        if view:
            bound = await _latest_view_artifact(conn, instance_id, view)
            if bound is None:
                continue
            aid, ver, ch = bound
            artifact_ref = {"artifact_id": aid, "version": ver, "content_hash": ch}
        starter_person = org.people.get(job_starter) if job_starter else None
        starter_is_sourcing = bool(
            starter_person and "sourcing_user" in (starter_person.roles or [])
        )
        if (
            event == "decision.brief_confirmed"
            and job_starter
            and person_id == job_starter
            and starter_is_sourcing
            and artifact_ref is not None
        ):
            if await _auto_confirm_brief_for_job_starter(
                conn,
                org,
                org_id,
                instance_id,
                dec=dec,
                person_id=person_id,
                artifact_ref=artifact_ref,
                definition=definition,
                defs=defs,
                packs_dir=packs_dir,
            ):
                opened.append(f"auto:{event}")
                continue
        select_min = _selection_minimum(definition, event) if dec.selection else None
        if event == "decision.supplier_selected" and select_min:
            detail = "Choose the vendor you are awarding this order to."
        elif event == "decision.master_rfp_confirmed":
            detail = (
                "Read the master RFP in the work panel. Save edits there if needed, then confirm to "
                "release vendor invitation drafting to sourcing."
            )
        elif select_min:
            detail = f"Choose at least {select_min}."
        else:
            detail = ""
        stored_ref = dict(artifact_ref) if artifact_ref is not None else None
        if select_min is not None and stored_ref is not None:
            stored_ref["select_min"] = select_min
        pending_id = ids.new_pending_id()
        pending_doc = _pending_payload(
            pending_id=pending_id,
            instance_id=instance_id,
            event=event,
            title=dec.label,
            for_role=dec.for_,
            for_person_id=person_id,
            artifact_ref=artifact_ref,
            created_at=ts,
            detail=detail,
            select_min=select_min if stored_ref is not None else None,
        )
        await conn.execute(
            "insert into work.pending_items ("
            " id, instance_id, kind, event, title, detail, for_role, for_person_id,"
            " options, artifact_ref, status, created_at"
            ") values (%s, %s, 'decision', %s, %s, %s, %s, %s, %s, %s, 'open', %s)",
            (
                pending_id,
                instance_id,
                event,
                dec.label,
                detail,
                dec.for_,
                person_id,
                Jsonb(pending_doc["options"]),
                Jsonb(stored_ref) if stored_ref else None,
                ts,
            ),
        )
        await _emit_pending_created(conn, instance_id=instance_id, person_id=person_id, pending=pending_doc)
        from .progress import post_decision_opened_progress

        inst_org_cur = await conn.execute(
            "select org_id from work.instances where id = %s",
            (instance_id,),
        )
        org_row = await inst_org_cur.fetchone()
        if org_row:
            await post_decision_opened_progress(
                conn,
                org=org,
                org_id=str(org_row[0]),
                instance_id=instance_id,
                pending_id=pending_id,
                label=dec.label,
                for_person_id=person_id,
                for_role=dec.for_,
            )
        opened.append(pending_id)
    return opened


def _row_key_values(content: dict[str, Any], row_key: str) -> set[str]:
    rows = content.get("rows")
    if not isinstance(rows, list):
        return set()
    out: set[str] = set()
    for row in rows:
        if isinstance(row, dict) and row_key in row and row[row_key] is not None:
            out.add(str(row[row_key]))
    return out


def _validate_selection(
    selection: list[str],
    *,
    row_key: str,
    content: dict[str, Any],
) -> None:
    if len(selection) != len(set(selection)):
        raise DecisionError(
            "validation_failed",
            422,
            "Invalid selection",
            "Each item may appear only once.",
        )
    allowed = _row_key_values(content, row_key)
    bad = [s for s in selection if s not in allowed]
    if bad:
        raise DecisionError(
            "validation_failed",
            422,
            "Invalid selection",
            "One or more selected items are not in the current version.",
        )


def _apply_sets(
    attributes: dict[str, Any],
    dec: WorkflowDecisionSpec,
    *,
    artifact_version: int | None,
    selection: list[str] | None,
) -> dict[str, Any]:
    out = dict(attributes)
    for attr_key, setter in dec.sets.items():
        if setter == "artifact_version":
            if artifact_version is None:
                raise DecisionError(
                    "validation_failed",
                    422,
                    "Artifact version required",
                    "This decision is bound to an artifact version.",
                )
            out[attr_key] = int(artifact_version)
        elif setter == "selection_count":
            if selection is None:
                raise DecisionError(
                    "validation_failed",
                    422,
                    "Selection required",
                    "Choose one or more items before confirming.",
                )
            out[attr_key] = len(selection)
    return out


async def _auto_confirm_brief_for_job_starter(
    conn: AsyncConnection,
    org: OrgModel,
    org_id: str,
    instance_id: str,
    *,
    dec: WorkflowDecisionSpec,
    person_id: str,
    artifact_ref: dict[str, Any],
    definition: WorkflowDefinition,
    defs: dict[str, Any],
    packs_dir: Path,
) -> bool:
    """When the person who started the job is also the brief confirmer, skip the self-approval card."""
    inst_cur = await conn.execute(
        "select state, version, attributes, correlation_id from work.instances where id = %s for update",
        (instance_id,),
    )
    inst = await inst_cur.fetchone()
    if inst is None:
        return False
    from_state, inst_version, attributes_raw, _correlation_id = inst[0], inst[1], inst[2], inst[3]
    attributes = attributes_raw if isinstance(attributes_raw, dict) else json.loads(attributes_raw or "{}")
    bound_ver = int(artifact_ref["version"])
    acur = await conn.execute(
        "select latest_version from work.artifacts where id = %s",
        (artifact_ref["artifact_id"],),
    )
    arow = await acur.fetchone()
    if arow is None or int(arow[0]) != bound_ver:
        return False

    new_attributes = _apply_sets(
        attributes,
        dec,
        artifact_version=bound_ver,
        selection=None,
    )
    changed_attrs = {k for k in dec.sets if attributes.get(k) != new_attributes.get(k)}
    event = "decision.brief_confirmed"
    ts = clock.now()
    decision_id = ids.new_decision_id()
    roles = await conn.execute(
        "select role from work.participants where instance_id = %s and person_id = %s",
        (instance_id, person_id),
    )
    actor_roles = [r[0] for r in await roles.fetchall()]
    actor_role = actor_roles[0] if actor_roles else dec.for_

    await conn.execute(
        "update work.instances set attributes = %s where id = %s",
        (Jsonb(new_attributes), instance_id),
    )
    apply_result = await workflow.apply_event(
        conn,
        instance_id,
        event,
        by_role=dec.for_,
        decision_id=decision_id,
        packs_dir=packs_dir,
        org=org,
        actor={"kind": "person", "id": person_id},
    )
    resulting_state = apply_result.to_state if apply_result.applied else str(from_state)

    from . import events as workflow_events

    await workflow_events.evaluate_attribute_triggers(
        conn,
        org,
        instance_id,
        changed=changed_attrs,
        packs_dir=packs_dir,
    )

    from .progress import post_decision_resolved_progress

    from_spec = definition.spec.states.get(str(from_state))
    unchanged_label = from_spec.label if from_spec is not None else from_state
    await post_decision_resolved_progress(
        conn,
        org=org,
        org_id=org_id,
        instance_id=instance_id,
        decider_id=person_id,
        decision_label=dec.label,
        job_moved=apply_result.applied,
        state_label_if_unchanged=str(unchanged_label or from_state),
        selection=None,
        row_key=None,
        bound_content=None,
        note=None,
    )

    if apply_result.applied:
        await conn.execute(
            "update work.artifacts set status = 'final' where id = %s",
            (artifact_ref["artifact_id"],),
        )

    record_body = _decision_record_response(
        decision_id=decision_id,
        instance_id=instance_id,
        event=event,
        value="confirm",
        actor=person_id,
        role=actor_role,
        at=ts,
        artifact_ref=artifact_ref,
        resulting_state=resulting_state,
    )
    await conn.execute(
        "insert into gov.decision_records ("
        " id, org_id, subject_kind, subject_id, event, value, actor, actor_role,"
        " artifact_ref, selection, idempotency_key, request_hash, response"
        ") values (%s, %s, 'instance', %s, %s, %s, %s, %s, %s, null, null, null, null)",
        (
            decision_id,
            org_id,
            instance_id,
            event,
            "confirm",
            person_id,
            actor_role,
            Jsonb(artifact_ref),
        ),
    )
    await audit_store.record(
        conn,
        org_id=org_id,
        actor=person_id,
        action=event,
        subject=f"instance:{instance_id}",
        data={"decision_id": decision_id, "value": "confirm", "resulting_state": resulting_state, "auto": True},
    )
    return apply_result.applied


def _decision_record_response(
    *,
    decision_id: str,
    instance_id: str,
    event: str,
    value: str,
    actor: str,
    role: str | None,
    at: datetime,
    artifact_ref: dict[str, Any] | None,
    resulting_state: str | None,
) -> dict[str, Any]:
    return {
        "decision_id": decision_id,
        "instance_id": instance_id,
        "event": event,
        "value": value,
        "by": actor,
        "role": role,
        "at": at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "artifact_ref": artifact_ref,
        "resulting_state": resulting_state,
    }


async def decide_pending(
    conn: AsyncConnection,
    org: OrgModel,
    org_id: str,
    pending_id: str,
    person_id: str,
    body: dict[str, Any],
    *,
    idempotency_key: str | None,
    packs_dir: Path,
) -> dict[str, Any]:
    req_hash = _decision_request_hash(pending_id, body)
    if idempotency_key:
        cur = await conn.execute(
            "select request_hash, response from gov.decision_records"
            " where org_id = %s and actor = %s and idempotency_key = %s",
            (org_id, person_id, idempotency_key),
        )
        prev = await cur.fetchone()
        if prev is not None:
            stored_hash, response = prev[0], prev[1]
            if stored_hash != req_hash:
                raise DecisionError(
                    "validation_failed",
                    422,
                    "Idempotency key reused",
                    "The same Idempotency-Key was used with a different request body.",
                )
            if isinstance(response, dict):
                return response
            return json.loads(response) if isinstance(response, str) else dict(response)

    pend_cur = await conn.execute(
        "select instance_id, kind, event, for_person_id, for_role, artifact_ref, status"
        " from work.pending_items where id = %s",
        (pending_id,),
    )
    pend_row = await pend_cur.fetchone()
    if pend_row is None:
        raise DecisionError("not_found", 404, "Pending item not found", f"No pending item {pending_id!r}.")
    instance_id, kind, event, for_person, for_role, artifact_ref_raw, pend_status = pend_row
    if kind != "decision":
        raise DecisionError("conflict", 409, "Not a decision", "This pending item is not a decision card.")

    inst_cur = await conn.execute(
        "select org_id, workflow, pack_version_id, state, version, status, attributes, correlation_id"
        " from work.instances where id = %s for update",
        (instance_id,),
    )
    inst = await inst_cur.fetchone()
    if inst is None:
        raise DecisionError("not_found", 404, "Job not found", f"No instance {instance_id!r}.")
    (
        inst_org,
        workflow_name,
        pack_version_id,
        from_state,
        inst_version,
        inst_status,
        attributes_raw,
        _correlation_id,
    ) = inst
    if inst_org != org_id:
        raise DecisionError("not_found", 404, "Pending item not found", f"No pending item {pending_id!r}.")

    await conn.execute("select id from work.pending_items where id = %s for update", (pending_id,))
    pend_cur2 = await conn.execute(
        "select status, for_person_id, artifact_ref from work.pending_items where id = %s",
        (pending_id,),
    )
    pend2 = await pend_cur2.fetchone()
    if pend2 is None:
        raise DecisionError("not_found", 404, "Pending item not found", f"No pending item {pending_id!r}.")
    pend_status, for_person, artifact_ref_raw = pend2[0], pend2[1], pend2[2]

    if pend_status != "open":
        raise DecisionError(
            "conflict",
            409,
            "Decision already handled",
            "This decision card is no longer open.",
        )
    if for_person != person_id:
        raise DecisionError(
            "not_permitted",
            403,
            "Not your decision",
            "Only the participant this item waits on may answer it.",
        )

    if str(event) == "task.retry":
        from .task_retry import decide_task_retry

        return await decide_task_retry(
            conn,
            org,
            org_id,
            pending_id,
            person_id,
            body,
            idempotency_key=idempotency_key,
            packs_dir=packs_dir,
        )

    expected = body.get("expected_version")
    if expected is None or int(expected) != int(inst_version):
        raise DecisionError(
            "stale_version",
            409,
            "Job changed",
            "Reload the job and try again.",
            current_version=int(inst_version),
        )

    dname = _decision_name_from_event(str(event))
    wcur = await conn.execute(
        "select spec from registry.definitions where pack_version_id = %s and kind = 'WorkflowDefinition'"
        " and name = %s",
        (str(pack_version_id), workflow_name),
    )
    wrow = await wcur.fetchone()
    wdoc = wrow[0] if isinstance(wrow[0], dict) else json.loads(wrow[0])
    definition = WorkflowDefinition.model_validate(wdoc)
    defs = await workflow._load_definitions(conn, str(pack_version_id))
    dec = definition.spec.decisions.get(dname)
    if dec is None:
        raise DecisionError("internal", 500, "Decision undefined", f"No decision {dname!r} on workflow.")

    artifact_ref = artifact_ref_raw if isinstance(artifact_ref_raw, dict) else (
        json.loads(artifact_ref_raw) if artifact_ref_raw else None
    )
    body_artifact_version = body.get("artifact_version")
    bound_content: dict[str, Any] | None = None
    if artifact_ref is not None:
        bound_ver = int(artifact_ref["version"])
        if body_artifact_version is None or int(body_artifact_version) != bound_ver:
            raise DecisionError(
                "stale_version",
                409,
                "Version changed",
                "Reload and confirm the current version.",
                current_version=bound_ver,
            )
        aid = artifact_ref["artifact_id"]
        acur = await conn.execute(
            "select latest_version from work.artifacts where id = %s",
            (aid,),
        )
        arow = await acur.fetchone()
        if arow is None or int(arow[0]) != bound_ver:
            raise DecisionError(
                "stale_version",
                409,
                "Version changed",
                "Reload and confirm the current version.",
                current_version=int(arow[0]) if arow else bound_ver,
            )
        vcur = await conn.execute(
            "select content from work.artifact_versions where artifact_id = %s and version = %s",
            (aid, bound_ver),
        )
        vrow = await vcur.fetchone()
        if vrow is not None:
            bound_content = vrow[0] if isinstance(vrow[0], dict) else json.loads(vrow[0])

    selection = body.get("selection")
    if dec.selection and (selection is None or not isinstance(selection, list) or len(selection) == 0):
        raise DecisionError(
            "validation_failed",
            422,
            "Selection required",
            "Choose one or more items before confirming.",
        )
    if dec.selection and isinstance(selection, list):
        # Fail closed: a selection is only accepted when it can be checked against the bound rows.
        view_name = definition.spec.states[dec.state].view
        raw_at = defs.get("ArtifactType", {}).get(view_name) if view_name else None
        at = ArtifactType.model_validate(raw_at) if raw_at is not None else None
        if (
            artifact_ref is None
            or bound_content is None
            or at is None
            or not at.spec.row_based
            or not at.spec.row_key
        ):
            raise DecisionError(
                "validation_failed",
                422,
                "Invalid selection",
                "There are no rows to select from for this decision.",
            )
        _validate_selection(
            [str(s) for s in selection],
            row_key=at.spec.row_key,
            content=bound_content,
        )

    attributes = attributes_raw if isinstance(attributes_raw, dict) else json.loads(attributes_raw or "{}")
    new_attributes = _apply_sets(
        attributes,
        dec,
        artifact_version=int(body_artifact_version) if body_artifact_version is not None else None,
        selection=selection if isinstance(selection, list) else None,
    )
    changed_attrs = {k for k in dec.sets if attributes.get(k) != new_attributes.get(k)}

    value = str(body.get("value") or "confirm")
    ts = clock.now()
    decision_id = ids.new_decision_id()
    roles = await conn.execute(
        "select role from work.participants where instance_id = %s and person_id = %s",
        (instance_id, person_id),
    )
    actor_roles = [r[0] for r in await roles.fetchall()]
    actor_role = actor_roles[0] if actor_roles else for_role

    selection_json = Jsonb(selection) if isinstance(selection, list) else None
    await conn.execute(
        "update work.instances set attributes = %s where id = %s",
        (Jsonb(new_attributes), instance_id),
    )

    await conn.execute(
        "update work.pending_items set status = 'resolved', resolved_at = %s, resolved_by = %s where id = %s",
        (ts, person_id, pending_id),
    )
    await _emit_pending_resolved(
        conn,
        instance_id=instance_id,
        person_id=person_id,
        pending_id=pending_id,
        outcome="resolved",
        by=person_id,
    )
    apply_result = await workflow.apply_event(
        conn,
        instance_id,
        str(event),
        by_role=dec.for_,
        decision_id=decision_id,
        packs_dir=packs_dir,
        org=org,
        actor={"kind": "person", "id": person_id},
    )
    resulting_state = apply_result.to_state if apply_result.applied else from_state

    from . import events as workflow_events

    await workflow_events.evaluate_attribute_triggers(
        conn,
        org,
        instance_id,
        changed=changed_attrs,
        packs_dir=packs_dir,
    )

    from .progress import post_decision_resolved_progress

    from_spec = definition.spec.states.get(from_state) if from_state else None
    unchanged_label = from_spec.label if from_spec is not None else from_state
    row_key: str | None = None
    if dec.selection and view_name:
        raw_at = defs.get("ArtifactType", {}).get(str(view_name))
        at_sel = ArtifactType.model_validate(raw_at) if raw_at is not None else None
        if at_sel is not None and at_sel.spec.row_key:
            row_key = str(at_sel.spec.row_key)
    note_raw = body.get("note")
    await post_decision_resolved_progress(
        conn,
        org=org,
        org_id=org_id,
        instance_id=instance_id,
        decider_id=person_id,
        decision_label=dec.label,
        job_moved=apply_result.applied,
        state_label_if_unchanged=str(unchanged_label or from_state),
        selection=[str(s) for s in selection] if isinstance(selection, list) else None,
        row_key=row_key,
        bound_content=bound_content,
        note=str(note_raw).strip() if isinstance(note_raw, str) and note_raw.strip() else None,
    )

    if apply_result.applied and artifact_ref is not None:
        await conn.execute(
            "update work.artifacts set status = 'final' where id = %s",
            (artifact_ref["artifact_id"],),
        )

    record_body = _decision_record_response(
        decision_id=decision_id,
        instance_id=instance_id,
        event=str(event),
        value=value,
        actor=person_id,
        role=actor_role,
        at=ts,
        artifact_ref=artifact_ref,
        resulting_state=resulting_state,
    )

    await conn.execute(
        "insert into gov.decision_records ("
        " id, org_id, subject_kind, subject_id, event, value, actor, actor_role,"
        " artifact_ref, selection, idempotency_key, request_hash, response"
        ") values (%s, %s, 'instance', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            decision_id,
            org_id,
            instance_id,
            str(event),
            value,
            person_id,
            actor_role,
            Jsonb(artifact_ref) if artifact_ref else None,
            selection_json,
            idempotency_key,
            req_hash if idempotency_key else None,
            Jsonb(record_body) if idempotency_key else None,
        ),
    )
    await audit_store.record(
        conn,
        org_id=org_id,
        actor=person_id,
        action=str(event),
        subject=f"instance:{instance_id}",
        data={"decision_id": decision_id, "value": value, "resulting_state": resulting_state},
    )

    await open_ready_decisions(conn, instance_id, org=org, packs_dir=packs_dir)

    return record_body


async def void_open_decisions_for_artifact(
    conn: AsyncConnection,
    *,
    instance_id: str,
    artifact_id: str,
    voided_by: str,
) -> int:
    """Void every open decision pending bound to this artifact. Returns how many were voided."""
    cur = await conn.execute(
        "select id, for_person_id from work.pending_items"
        " where instance_id = %s and status = 'open' and kind = 'decision'"
        " and artifact_ref->>'artifact_id' = %s"
        " for update",
        (instance_id, artifact_id),
    )
    rows = await cur.fetchall()
    if not rows:
        return 0
    ts = clock.now()
    for pending_id, for_person in rows:
        await conn.execute(
            "update work.pending_items set status = 'voided', resolved_at = %s, resolved_by = %s where id = %s",
            (ts, voided_by, pending_id),
        )
        await _emit_pending_resolved(
            conn,
            instance_id=instance_id,
            person_id=for_person,
            pending_id=pending_id,
            outcome="voided",
            by=voided_by,
        )
    return len(rows)
