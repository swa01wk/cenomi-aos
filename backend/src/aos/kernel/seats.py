"""Seat lifecycle FSM, configuration checks and projections (M1-BE-03)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import Any

from psycopg import AsyncConnection
from psycopg.errors import UniqueViolation
from psycopg.types.json import Jsonb

from ..model_registry import model_alias_registered
from . import audit_store, ids
from .org import OrgModel
from .outbox import OutboxRow, append_outbox_many

CHECK_NAMES = (
    "pack_version_published",
    "skill_work_types_allowed",
    "authority_resources_exist",
    "committed_effect_governed",
    "model_alias_resolves",
    "placement_team_valid",
)

RULE_NOT_CONFIGURER = "seat.activate.not_configurer"
RULE_NOT_OWNER = "seat.activate.not_owner"


@dataclass(frozen=True)
class CommittedRefusal:
    code: str
    status: int
    title: str
    detail: str
    decision_id: str
    rule: str | None = None


@dataclass(frozen=True)
class EvalRunJob:
    run_id: str
    suite: str


class SeatError(Exception):
    def __init__(self, code: str, status: int, title: str, detail: str = "", **extra: Any) -> None:
        self.code = code
        self.status = status
        self.title = title
        self.detail = detail
        self.extra = extra
        super().__init__(title)


def resolve_owner_person_id(org: OrgModel, owner: str) -> str:
    if owner in org.people:
        return owner
    raise SeatError(
        "validation_failed",
        422,
        "Invalid seat owner",
        f"Seat owner {owner!r} is not a person in the organization.",
    )


def seat_audience(org: OrgModel, *, owner_person_id: str, placement: str) -> list[str]:
    people = {owner_person_id}
    for pid, person in org.people.items():
        if person.team == placement:
            people.add(pid)
    return sorted(people)


async def insert_seats_for_published_pack(
    conn: AsyncConnection,
    *,
    org: OrgModel,
    org_id: str,
    pack_version_id: str,
) -> None:
    cur = await conn.execute(
        "select name, version, spec from registry.definitions"
        " where pack_version_id = %s and kind = 'Seat'",
        (pack_version_id,),
    )
    for name, version, spec in await cur.fetchall():
        doc = spec if isinstance(spec, dict) else json.loads(spec)
        seat_spec = doc.get("spec") or {}
        meta = doc.get("metadata") or {}
        owner = meta.get("owner") or ""
        owner_person_id = resolve_owner_person_id(org, owner)
        await conn.execute(
            "insert into registry.seats ("
            " org_id, name, version, pack_version_id, display_name, placement, owner_person_id, state"
            ") values (%s, %s, %s, %s, %s, %s, %s, 'DRAFT')"
            " on conflict (org_id, name, version) do nothing",
            (
                org_id,
                name,
                version,
                pack_version_id,
                seat_spec.get("display_name", name),
                seat_spec.get("placement", ""),
                owner_person_id,
            ),
        )


def _availability(state: str, running_attempts: int) -> str:
    if state == "ACTIVE":
        return "BUSY" if running_attempts > 0 else "AVAILABLE"
    return "UNAVAILABLE"


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


def _seat_definition(defs: dict[str, dict[str, dict]], seat_name: str) -> dict:
    seat = defs.get("Seat", {}).get(seat_name)
    if seat is None:
        raise SeatError("not_found", 404, "Seat definition not found", f"No Seat {seat_name!r} on this pack version.")
    return seat


def _iter_tools(defs: dict[str, dict[str, dict]]) -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = []
    for pname, prov in defs.get("ToolProvider", {}).items():
        for tname, tool in (prov.get("spec") or {}).get("tools", {}).items():
            out.append((f"{pname}/{tname}", tool))
    return out


def _run_configuration_checks(
    *,
    org: OrgModel,
    defs: dict[str, dict[str, dict]],
    seat_name: str,
    pack_version_status: str,
) -> list[dict[str, Any]]:
    seat_doc = _seat_definition(defs, seat_name)
    spec = seat_doc.get("spec") or {}
    checks: list[dict[str, Any]] = []

    published = pack_version_status == "published"
    checks.append(
        {
            "name": "pack_version_published",
            "passed": published,
            "detail": "" if published else f"pack version status is {pack_version_status!r}, not published",
        }
    )

    role_name = spec.get("role")
    role_doc = defs.get("Role", {}).get(role_name or "")
    role_wt = set((role_doc or {}).get("spec", {}).get("work_types") or [])
    skills_ok = True
    skill_detail: list[str] = []
    for sk in spec.get("skills") or []:
        skill_doc = defs.get("Skill", {}).get(sk)
        if skill_doc is None:
            skills_ok = False
            skill_detail.append(f"missing Skill {sk!r}")
            continue
        extra = set(skill_doc.get("spec", {}).get("work_types") or []) - role_wt
        if extra:
            skills_ok = False
            skill_detail.append(f"skill {sk!r} needs work types {sorted(extra)} not allowed on role {role_name!r}")
    checks.append(
        {
            "name": "skill_work_types_allowed",
            "passed": skills_ok and bool(role_doc),
            "detail": "; ".join(skill_detail) if skill_detail else ("" if role_doc else f"role {role_name!r} missing"),
        }
    )

    prof_ref = spec.get("authority_profile") or ""
    prof_name, _, prof_ver = prof_ref.partition("@")
    prof_doc = defs.get("Policy", {}).get(prof_name)
    resources_ok = True
    res_detail: list[str] = []
    seat_resources = set(spec.get("resources") or [])
    for r in seat_resources:
        if r not in defs.get("Resource", {}):
            resources_ok = False
            res_detail.append(f"missing Resource {r!r}")
    if prof_doc is None or prof_doc.get("spec", {}).get("type") != "authority_profile":
        resources_ok = False
        res_detail.append(f"authority profile {prof_name!r} missing or wrong type")
    elif str(prof_doc.get("metadata", {}).get("version")) != prof_ver and prof_ver:
        resources_ok = False
        res_detail.append(f"authority profile version pin {prof_ver!r} does not match pack")
    elif prof_doc:
        for grant in prof_doc.get("spec", {}).get("grants") or []:
            if grant.get("resource") not in seat_resources:
                resources_ok = False
                res_detail.append(f"profile grants resource {grant.get('resource')!r} not on seat")
    checks.append(
        {
            "name": "authority_resources_exist",
            "passed": resources_ok,
            "detail": "; ".join(res_detail),
        }
    )

    rules_by_action: dict[str, list] = {}
    for pol in defs.get("Policy", {}).values():
        for rule in pol.get("spec", {}).get("rules") or []:
            rules_by_action.setdefault(rule.get("action"), []).append(rule)

    gov_ok = True
    gov_detail: list[str] = []
    autonomy = spec.get("autonomy_mode", "supervised")
    if prof_doc and prof_doc.get("spec", {}).get("type") == "authority_profile":
        grants = prof_doc.get("spec", {}).get("grants") or []
        for tlabel, tool in _iter_tools(defs):
            tool_class = tool.get("class") or tool.get("tool_class")
            resource = tool.get("resource")
            if tool_class != "committed_effect" or resource not in seat_resources:
                continue
            if not tool.get("reconcile_with"):
                gov_ok = False
                gov_detail.append(f"tool {tlabel} has no reconcile_with")
            action = f"{resource}.{tool.get('action')}"
            effects = {
                g.get("effect")
                for g in grants
                if g.get("resource") == resource and tool.get("action") in (g.get("actions") or [])
            }
            if "ALLOW" in effects and autonomy == "supervised":
                gov_ok = False
                gov_detail.append(f"supervised seat may {action} without approval")
            if "REQUIRE_APPROVAL" in effects and not any(
                r.get("effect") == "REQUIRE_APPROVAL" for r in rules_by_action.get(action, [])
            ):
                gov_ok = False
                gov_detail.append(f"{action} requires approval but no gate rule")
    checks.append(
        {"name": "committed_effect_governed", "passed": gov_ok, "detail": "; ".join(gov_detail)},
    )

    alias = (spec.get("runtime") or {}).get("model_alias") or ""
    alias_ok = bool(alias) and model_alias_registered(alias)
    checks.append(
        {
            "name": "model_alias_resolves",
            "passed": alias_ok,
            "detail": "" if alias_ok else f"model alias {alias!r} is not registered",
        }
    )

    placement = spec.get("placement") or ""
    teams = {f"{d}/{t}" for d, dept in org.departments.items() for t in dept.teams}
    placement_ok = placement in teams
    team_owner_ok = False
    team_detail = ""
    if placement_ok:
        dept_id, team_id = placement.split("/", 1)
        team = org.departments[dept_id].teams[team_id]
        team_owner_ok = team.owner in org.people
        if not team_owner_ok:
            team_detail = f"team owner {team.owner!r} is not a person in the organization"
    else:
        team_detail = f"no team {placement!r}"
    checks.append(
        {
            "name": "placement_team_valid",
            "passed": placement_ok and team_owner_ok,
            "detail": team_detail,
        }
    )
    return checks


async def _lock_seat_row(
    conn: AsyncConnection, org_id: str, name: str, version: int
) -> tuple | None:
    cur = await conn.execute(
        "select name, version, pack_version_id, display_name, placement, owner_person_id, state,"
        " configured_by, activated_by, record_version, updated_at"
        " from registry.seats"
        " where org_id = %s and name = %s and version = %s"
        " for update",
        (org_id, name, version),
    )
    return await cur.fetchone()


async def _pack_version_status(conn: AsyncConnection, org_id: str, pack_version_id: str) -> str:
    cur = await conn.execute(
        "select status from registry.pack_versions where id = %s and org_id = %s",
        (pack_version_id, org_id),
    )
    row = await cur.fetchone()
    return row[0] if row else "missing"


async def _upsert_checks(
    conn: AsyncConnection,
    *,
    org_id: str,
    seat: str,
    seat_version: int,
    checks: list[dict[str, Any]],
) -> None:
    for chk in checks:
        await conn.execute(
            "insert into registry.seat_checks (org_id, seat, seat_version, name, passed, detail)"
            " values (%s, %s, %s, %s, %s, %s)"
            " on conflict (org_id, seat, seat_version, name)"
            " do update set passed = excluded.passed, detail = excluded.detail, checked_at = now()",
            (org_id, seat, seat_version, chk["name"], chk["passed"], chk.get("detail") or ""),
        )


async def _seat_event(
    conn: AsyncConnection,
    *,
    org_id: str,
    seat: str,
    seat_version: int,
    from_state: str | None,
    to_state: str,
    actor: str,
    decision_id: str | None = None,
    note: str | None = None,
) -> None:
    await conn.execute(
        "insert into registry.seat_events (org_id, seat, seat_version, from_state, to_state, actor, decision_id, note)"
        " values (%s, %s, %s, %s, %s, %s, %s, %s)",
        (org_id, seat, seat_version, from_state, to_state, actor, decision_id, note),
    )


async def _emit_state_changed(
    conn: AsyncConnection,
    org: OrgModel,
    *,
    seat: str,
    from_state: str,
    to_state: str,
    owner_person_id: str,
    placement: str,
) -> None:
    audience_ids = seat_audience(org, owner_person_id=owner_person_id, placement=placement)
    rows = [
        OutboxRow(
            stream=ids.stream_user(pid),
            event_type="seat.state_changed",
            instance_id=None,
            audience={"person_id": pid},
            data={"seat": seat, "from": from_state, "to": to_state},
        )
        for pid in audience_ids
    ]
    if rows:
        await append_outbox_many(conn, rows)


async def _insert_decision(
    conn: AsyncConnection,
    *,
    org_id: str,
    seat: str,
    event: str,
    value: str,
    actor: str,
    actor_role: str | None,
    decision_id: str,
) -> None:
    await conn.execute(
        "insert into gov.decision_records ("
        " id, org_id, subject_kind, subject_id, event, value, actor, actor_role"
        ") values (%s, %s, 'seat', %s, %s, %s, %s, %s)",
        (decision_id, org_id, seat, event, value, actor, actor_role),
    )


def _primary_role(roles: list[str]) -> str | None:
    return roles[0] if roles else None


async def _find_other_live_seat(
    conn: AsyncConnection, org_id: str, name: str, seat_version: int
) -> tuple | None:
    cur = await conn.execute(
        "select version, state from registry.seats"
        " where org_id = %s and name = %s and version <> %s and state in ('ACTIVE', 'PAUSED')"
        " limit 1",
        (org_id, name, seat_version),
    )
    return await cur.fetchone()


async def _running_attempts(conn: AsyncConnection, org_id: str, seat: str) -> int:
    cur = await conn.execute(
        "select count(*) from work.attempts a"
        " join work.tasks t on t.id = a.task_id"
        " join work.instances i on i.id = t.instance_id"
        " where i.org_id = %s and i.seat = %s and a.state in ('ADMITTED', 'CLAIMED')",
        (org_id, seat),
    )
    row = await cur.fetchone()
    return int(row[0]) if row else 0


async def _spend_today(conn: AsyncConnection, org_id: str, seat: str) -> tuple[float, float]:
    cur = await conn.execute(
        "select coalesce(limit_usd, 0), coalesce(settled_usd, 0) + coalesce(reserved_usd, 0)"
        " from gov.budget_ledger where org_id = %s and seat = %s and day = %s",
        (org_id, seat, date.today()),
    )
    row = await cur.fetchone()
    if row is None:
        return 0.0, 0.0
    return float(row[0]), float(row[1])


async def _fetch_checks(conn: AsyncConnection, org_id: str, seat: str, seat_version: int) -> list[dict]:
    cur = await conn.execute(
        "select name, passed, detail from registry.seat_checks"
        " where org_id = %s and seat = %s and seat_version = %s order by name",
        (org_id, seat, seat_version),
    )
    return [{"name": n, "passed": p, "detail": d or ""} for n, p, d in await cur.fetchall()]


async def _fetch_evals(conn: AsyncConnection, org_id: str, seat: str, seat_version: int) -> list[dict]:
    cur = await conn.execute(
        "select distinct on (suite) id, suite, model, status, passed, total, detail, finished_at"
        " from registry.eval_runs"
        " where org_id = %s and seat = %s and seat_version = %s"
        " order by suite, started_at desc",
        (org_id, seat, seat_version),
    )
    out = []
    for rid, suite, model, status, passed, total, detail, finished_at in await cur.fetchall():
        if isinstance(detail, str):
            try:
                detail = json.loads(detail) if detail else {}
            except json.JSONDecodeError:
                detail = {"legacy": detail}
        elif detail is None:
            detail = {}
        out.append(
            {
                "id": rid,
                "suite": suite,
                "model": model,
                "status": status,
                "passed": passed,
                "total": total,
                "detail": detail,
                "finished_at": finished_at.isoformat() if finished_at else None,
            }
        )
    return out


async def _fetch_history(conn: AsyncConnection, org_id: str, seat: str, seat_version: int) -> list[dict]:
    cur = await conn.execute(
        "select from_state, to_state, actor, at, decision_id from registry.seat_events"
        " where org_id = %s and seat = %s and seat_version = %s order by at",
        (org_id, seat, seat_version),
    )
    return [
        {
            "from": fs,
            "to": ts,
            "by": actor,
            "at": at.isoformat(),
            "decision_id": did,
        }
        for fs, ts, actor, at, did in await cur.fetchall()
    ]


async def _limits_from_pack(conn: AsyncConnection, pack_version_id: str, seat_name: str) -> dict | None:
    spec = await conn.execute(
        "select spec from registry.definitions where pack_version_id = %s and kind = 'Seat' and name = %s",
        (pack_version_id, seat_name),
    )
    row = await spec.fetchone()
    if row is None:
        return None
    doc = row[0] if isinstance(row[0], dict) else json.loads(row[0])
    limits = (doc.get("spec") or {}).get("limits")
    if not limits:
        return None
    return {
        "run_minutes": limits.get("run_minutes"),
        "actions_per_run": limits.get("actions_per_run"),
        "daily_cost_usd": limits.get("daily_cost_usd"),
    }


async def project_seat_detail(
    conn: AsyncConnection,
    org_id: str,
    row: tuple,
) -> dict[str, Any]:
    (
        name,
        version,
        pack_version_id,
        display_name,
        placement,
        owner_person_id,
        state,
        configured_by,
        _activated_by,
        record_version,
        _updated_at,
    ) = row
    running = await _running_attempts(conn, org_id, name)
    daily_limit, spend = await _spend_today(conn, org_id, name)
    limits = await _limits_from_pack(conn, str(pack_version_id), name)
    body: dict[str, Any] = {
        "name": name,
        "display_name": display_name,
        "version": version,
        "pack_version": str(pack_version_id),
        "placement": placement,
        "state": state,
        "availability": _availability(state, running),
        "running_attempts": running,
        "spend_today_usd": spend,
        "daily_limit_usd": daily_limit,
        "owner": owner_person_id,
        "record_version": record_version,
        "configured_by": configured_by,
        "checks": await _fetch_checks(conn, org_id, name, version),
        "evals": await _fetch_evals(conn, org_id, name, version),
        "history": await _fetch_history(conn, org_id, name, version),
    }
    if limits:
        body["limits"] = limits
    return body


async def list_seats(conn: AsyncConnection, org_id: str) -> list[dict[str, Any]]:
    cur = await conn.execute(
        "select name, version, pack_version_id, display_name, placement, owner_person_id, state,"
        " configured_by, activated_by, record_version, updated_at"
        " from registry.seats where org_id = %s order by name, version desc",
        (org_id,),
    )
    items = []
    for row in await cur.fetchall():
        items.append(await project_seat_detail(conn, org_id, row))
    return items


async def get_seat(conn: AsyncConnection, org_id: str, name: str, *, version: int | None = None) -> dict[str, Any]:
    if version is not None:
        row = await _lock_seat_row(conn, org_id, name, version)
    else:
        cur = await conn.execute(
            "select name, version, pack_version_id, display_name, placement, owner_person_id, state,"
            " configured_by, activated_by, record_version, updated_at"
            " from registry.seats where org_id = %s and name = %s order by version desc limit 1",
            (org_id, name),
        )
        row = await cur.fetchone()
    if row is None:
        raise SeatError("not_found", 404, "Seat not found", f"No seat {name!r} in this organization.")
    return await project_seat_detail(conn, org_id, row)


async def configure_seat(
    conn: AsyncConnection,
    *,
    org: OrgModel,
    org_id: str,
    name: str,
    seat_version: int,
    expected_version: int,
    actor: str,
) -> dict[str, Any]:
    row = await _lock_seat_row(conn, org_id, name, seat_version)
    if row is None:
        raise SeatError("not_found", 404, "Seat not found", f"No seat {name!r} version {seat_version}.")
    if row[9] != expected_version:
        raise SeatError(
            "stale_version",
            409,
            "Seat changed since you loaded it",
            "Reload the seat and try again.",
            current_version=row[9],
        )
    if row[6] != "DRAFT":
        raise SeatError(
            "conflict",
            409,
            "Seat is not in DRAFT",
            f"Configure applies only to DRAFT seats; this seat is {row[6]!r}.",
        )

    pack_version_id = str(row[2])
    pv_status = await _pack_version_status(conn, org_id, pack_version_id)
    defs = await _load_definitions(conn, pack_version_id)
    checks = _run_configuration_checks(org=org, defs=defs, seat_name=name, pack_version_status=pv_status)
    await _upsert_checks(conn, org_id=org_id, seat=name, seat_version=seat_version, checks=checks)

    if all(c["passed"] for c in checks):
        from_state = row[6]
        new_record_version = row[9] + 1
        cur = await conn.execute(
            "update registry.seats set state = 'CONFIGURED', configured_by = %s,"
            " record_version = %s, updated_at = now()"
            " where org_id = %s and name = %s and version = %s and record_version = %s"
            " returning name, version, pack_version_id, display_name, placement, owner_person_id, state,"
            " configured_by, activated_by, record_version, updated_at",
            (actor, new_record_version, org_id, name, seat_version, expected_version),
        )
        updated = await cur.fetchone()
        if updated is None:
            raise SeatError(
                "stale_version",
                409,
                "Seat changed since you loaded it",
                "Reload the seat and try again.",
                current_version=row[9],
            )
        await _seat_event(
            conn,
            org_id=org_id,
            seat=name,
            seat_version=seat_version,
            from_state=from_state,
            to_state="CONFIGURED",
            actor=actor,
        )
        await audit_store.record(
            conn,
            org_id=org_id,
            actor=actor,
            action="seat.configured",
            subject=f"{name}@{seat_version}",
            data={"seat": name, "seat_version": seat_version, "pack_version_id": pack_version_id},
        )
        await _emit_state_changed(
            conn,
            org,
            seat=name,
            from_state=from_state,
            to_state="CONFIGURED",
            owner_person_id=row[5],
            placement=row[4],
        )
        return await project_seat_detail(conn, org_id, updated)

    return await project_seat_detail(conn, org_id, row)


async def definitions_for_pack_version(conn: AsyncConnection, pack_version_id: str) -> dict[str, dict[str, dict]]:
    return await _load_definitions(conn, pack_version_id)


async def eval_suite_file(conn: AsyncConnection, pack_version_id: str, suite_name: str) -> str | None:
    return await _suite_file(conn, pack_version_id, suite_name)


async def pack_version_digest(conn: AsyncConnection, pack_version_id: str) -> str:
    cur = await conn.execute(
        "select digest from registry.pack_versions where id = %s",
        (pack_version_id,),
    )
    row = await cur.fetchone()
    return row[0] if row else ""


async def _suite_file(conn: AsyncConnection, pack_version_id: str, suite_name: str) -> str | None:
    cur = await conn.execute(
        "select file from registry.definitions"
        " where pack_version_id = %s and kind = 'EvalSuite' and name = %s",
        (pack_version_id, suite_name),
    )
    row = await cur.fetchone()
    return row[0] if row else None


async def _mark_interrupted_eval_runs(
    conn: AsyncConnection, *, org_id: str, seat: str, seat_version: int
) -> None:
    await conn.execute(
        "update registry.eval_runs"
        " set status = 'failed', finished_at = now(),"
        " detail = coalesce(detail, '{}'::jsonb) || jsonb_build_object('reason', 'interrupted')"
        " where org_id = %s and seat = %s and seat_version = %s and status = 'running'"
        " and started_at < now() - interval '10 minutes'",
        (org_id, seat, seat_version),
    )


async def _has_recent_running_eval(
    conn: AsyncConnection, *, org_id: str, seat: str, seat_version: int
) -> bool:
    cur = await conn.execute(
        "select exists("
        " select 1 from registry.eval_runs"
        " where org_id = %s and seat = %s and seat_version = %s and status = 'running'"
        " and started_at >= now() - interval '10 minutes'"
        ")",
        (org_id, seat, seat_version),
    )
    row = await cur.fetchone()
    return bool(row[0]) if row else False


async def begin_seat_eval_runs(
    conn: AsyncConnection,
    *,
    org_id: str,
    name: str,
    seat_version: int,
    model: str,
) -> tuple[str, list[EvalRunJob], list[dict[str, Any]]]:
    """Insert running eval rows; return pack_version_id, jobs and 202 projection rows."""
    row = await _lock_seat_row(conn, org_id, name, seat_version)
    if row is None:
        raise SeatError("not_found", 404, "Seat not found", f"No seat {name!r} version {seat_version}.")
    state = row[6]
    if state not in ("CONFIGURED", "TESTING"):
        raise SeatError(
            "conflict",
            409,
            "Seat is not ready for evals",
            f"Eval runs require CONFIGURED or TESTING; this seat is {state!r}.",
        )
    pack_version_id = str(row[2])
    await _mark_interrupted_eval_runs(conn, org_id=org_id, seat=name, seat_version=seat_version)
    if await _has_recent_running_eval(conn, org_id=org_id, seat=name, seat_version=seat_version):
        raise SeatError(
            "conflict",
            409,
            "Eval runs already in progress",
            "Wait for the current sandbox runs to finish or try again after ten minutes.",
        )

    defs = await _load_definitions(conn, pack_version_id)
    seat_doc = defs.get("Seat", {}).get(name)
    if seat_doc is None:
        raise SeatError("not_found", 404, "Seat definition not found", f"No Seat {name!r} on this pack version.")
    suites = (seat_doc.get("spec") or {}).get("evals") or []
    jobs: list[EvalRunJob] = []
    started: list[dict[str, Any]] = []
    for suite in suites:
        if suite not in defs.get("EvalSuite", {}):
            raise SeatError(
                "conflict",
                409,
                "Eval suite missing from pack",
                f"Suite {suite!r} is listed on the Seat but not on the pinned pack version.",
            )
        run_id = ids.new_eval_run_id()
        await conn.execute(
            "insert into registry.eval_runs ("
            " id, org_id, seat, seat_version, suite, model, status, passed, total, detail"
            ") values (%s, %s, %s, %s, %s, %s, 'running', 0, 0, '{}'::jsonb)",
            (run_id, org_id, name, seat_version, suite, model),
        )
        jobs.append(EvalRunJob(run_id=run_id, suite=suite))
        started.append(
            {
                "id": run_id,
                "suite": suite,
                "model": model,
                "status": "running",
                "passed": 0,
                "total": 0,
                "detail": {},
                "finished_at": None,
            }
        )
    return pack_version_id, jobs, started


async def record_eval_run_result(
    conn: AsyncConnection,
    *,
    run_id: str,
    passed: int,
    total: int,
    status: str,
    detail: dict[str, Any],
) -> None:
    await conn.execute(
        "update registry.eval_runs"
        " set status = %s, passed = %s, total = %s, detail = %s, finished_at = now()"
        " where id = %s and status = 'running'",
        (status, passed, total, Jsonb(detail), run_id),
    )


async def maybe_promote_seat_to_testing(
    conn: AsyncConnection,
    *,
    org: OrgModel,
    org_id: str,
    name: str,
    seat_version: int,
) -> None:
    row = await _lock_seat_row(conn, org_id, name, seat_version)
    if row is None or row[6] != "CONFIGURED":
        return
    pack_version_id = str(row[2])
    if not await _eval_suites_passed(
        conn,
        org_id=org_id,
        seat_name=name,
        seat_version=seat_version,
        pack_version_id=pack_version_id,
        eval_strict=False,
    ):
        return
    from_state = row[6]
    new_record_version = row[9] + 1
    cur = await conn.execute(
        "update registry.seats set state = 'TESTING', record_version = %s, updated_at = now()"
        " where org_id = %s and name = %s and version = %s and record_version = %s and state = 'CONFIGURED'"
        " returning name, version, pack_version_id, display_name, placement, owner_person_id, state,"
        " configured_by, activated_by, record_version, updated_at",
        (new_record_version, org_id, name, seat_version, row[9]),
    )
    updated = await cur.fetchone()
    if updated is None:
        return
    await _seat_event(
        conn,
        org_id=org_id,
        seat=name,
        seat_version=seat_version,
        from_state=from_state,
        to_state="TESTING",
        actor="system",
    )
    await audit_store.record(
        conn,
        org_id=org_id,
        actor="system",
        action="seat.tested",
        subject=f"{name}@{seat_version}",
        data={"seat": name, "seat_version": seat_version, "pack_version_id": pack_version_id},
    )
    await _emit_state_changed(
        conn,
        org,
        seat=name,
        from_state=from_state,
        to_state="TESTING",
        owner_person_id=row[5],
        placement=row[4],
    )


async def _latest_eval_runs(
    conn: AsyncConnection, *, org_id: str, seat_name: str, seat_version: int
) -> list[tuple[str, str, dict]]:
    cur = await conn.execute(
        "select distinct on (suite) suite, status, detail"
        " from registry.eval_runs"
        " where org_id = %s and seat = %s and seat_version = %s"
        " order by suite, started_at desc",
        (org_id, seat_name, seat_version),
    )
    rows = []
    for suite, status, detail in await cur.fetchall():
        if isinstance(detail, dict):
            doc = detail
        elif isinstance(detail, str):
            try:
                doc = json.loads(detail) if detail else {}
            except json.JSONDecodeError:
                doc = {}
        else:
            doc = {}
        rows.append((suite, status, doc))
    return rows


def _detail_has_deferred(detail: dict[str, Any]) -> bool:
    if detail.get("deferred_count", 0) > 0:
        return True
    for item in detail.get("expectations") or []:
        if item.get("status") == "deferred":
            return True
    return False


async def _eval_suites_passed(
    conn: AsyncConnection,
    *,
    org_id: str,
    seat_name: str,
    seat_version: int,
    pack_version_id: str,
    eval_strict: bool,
) -> bool:
    defs = await _load_definitions(conn, pack_version_id)
    seat_doc = defs.get("Seat", {}).get(seat_name)
    if seat_doc is None:
        return False
    suites = (seat_doc.get("spec") or {}).get("evals") or []
    if not suites:
        return True
    latest = await _latest_eval_runs(conn, org_id=org_id, seat_name=seat_name, seat_version=seat_version)
    by_suite = {suite: (status, detail) for suite, status, detail in latest}
    for s in suites:
        entry = by_suite.get(s)
        if entry is None or entry[0] != "passed":
            return False
        if eval_strict and _detail_has_deferred(entry[1]):
            return False
    return True


def _raise_eval_gate_failed(*, eval_strict: bool, deferred: bool) -> None:
    if deferred and eval_strict:
        raise SeatError(
            "conflict",
            409,
            "Eval suites have deferred expectations",
            "AOS_EVAL_STRICT is on; every expectation must be satisfied before approval or activation.",
        )
    raise SeatError(
        "conflict",
        409,
        "Eval suites have not passed",
        "Every eval suite for this seat must have a latest run with status passed.",
    )


async def _require_eval_passed(
    conn: AsyncConnection,
    *,
    org_id: str,
    seat_name: str,
    seat_version: int,
    pack_version_id: str,
) -> None:
    latest = await _latest_eval_runs(
        conn, org_id=org_id, seat_name=seat_name, seat_version=seat_version
    )
    defs = await _load_definitions(conn, pack_version_id)
    seat_doc = defs.get("Seat", {}).get(seat_name)
    suites = (seat_doc.get("spec") or {}).get("evals") or [] if seat_doc else []
    by_suite = {suite: (status, detail) for suite, status, detail in latest}
    for s in suites:
        entry = by_suite.get(s)
        if entry is None or entry[0] != "passed":
            _raise_eval_gate_failed(eval_strict=False, deferred=False)


async def _require_eval_no_deferred(
    conn: AsyncConnection,
    *,
    org_id: str,
    seat_name: str,
    seat_version: int,
    pack_version_id: str,
) -> None:
    await _require_eval_passed(
        conn,
        org_id=org_id,
        seat_name=seat_name,
        seat_version=seat_version,
        pack_version_id=pack_version_id,
    )
    latest = await _latest_eval_runs(
        conn, org_id=org_id, seat_name=seat_name, seat_version=seat_version
    )
    defs = await _load_definitions(conn, pack_version_id)
    seat_doc = defs.get("Seat", {}).get(seat_name)
    suites = (seat_doc.get("spec") or {}).get("evals") or [] if seat_doc else []
    by_suite = {suite: (status, detail) for suite, status, detail in latest}
    for s in suites:
        entry = by_suite.get(s)
        if entry and _detail_has_deferred(entry[1]):
            _raise_eval_gate_failed(eval_strict=True, deferred=True)


async def approve_seat(
    conn: AsyncConnection,
    *,
    org: OrgModel,
    org_id: str,
    name: str,
    seat_version: int,
    expected_version: int,
    actor: str,
    roles: list[str],
    eval_strict: bool = False,
) -> dict[str, Any]:
    if "risk" not in roles:
        raise SeatError("not_permitted", 403, "Risk role required", "Only risk may approve a tested seat.")

    row = await _lock_seat_row(conn, org_id, name, seat_version)
    if row is None:
        raise SeatError("not_found", 404, "Seat not found", f"No seat {name!r} version {seat_version}.")
    if row[9] != expected_version:
        raise SeatError(
            "stale_version",
            409,
            "Seat changed since you loaded it",
            "Reload the seat and try again.",
            current_version=row[9],
        )
    if row[6] != "TESTING":
        raise SeatError(
            "conflict",
            409,
            "Seat is not ready for approval",
            f"Risk approval requires TESTING; this seat is {row[6]!r}.",
        )
    if eval_strict:
        await _require_eval_no_deferred(
            conn,
            org_id=org_id,
            seat_name=name,
            seat_version=seat_version,
            pack_version_id=str(row[2]),
        )
    else:
        await _require_eval_passed(
            conn,
            org_id=org_id,
            seat_name=name,
            seat_version=seat_version,
            pack_version_id=str(row[2]),
        )

    from_state = row[6]
    new_record_version = row[9] + 1
    cur = await conn.execute(
        "update registry.seats set state = 'APPROVED', record_version = %s, updated_at = now()"
        " where org_id = %s and name = %s and version = %s and record_version = %s"
        " returning name, version, pack_version_id, display_name, placement, owner_person_id, state,"
        " configured_by, activated_by, record_version, updated_at",
        (new_record_version, org_id, name, seat_version, expected_version),
    )
    updated = await cur.fetchone()
    if updated is None:
        raise SeatError(
            "stale_version",
            409,
            "Seat changed since you loaded it",
            "Reload the seat and try again.",
            current_version=row[9],
        )
    await _seat_event(
        conn,
        org_id=org_id,
        seat=name,
        seat_version=seat_version,
        from_state=from_state,
        to_state="APPROVED",
        actor=actor,
    )
    await audit_store.record(
        conn,
        org_id=org_id,
        actor=actor,
        action="seat.approved",
        subject=f"{name}@{seat_version}",
        data={"seat": name, "seat_version": seat_version},
    )
    await _emit_state_changed(
        conn,
        org,
        seat=name,
        from_state=from_state,
        to_state="APPROVED",
        owner_person_id=row[5],
        placement=row[4],
    )
    return await project_seat_detail(conn, org_id, updated)


async def _record_activate_denied(
    conn: AsyncConnection,
    *,
    org_id: str,
    seat: str,
    seat_version: int,
    actor: str,
    roles: list[str],
    rule: str,
    code: str,
    title: str,
    detail: str,
) -> CommittedRefusal:
    decision_id = ids.new_decision_id()
    await _insert_decision(
        conn,
        org_id=org_id,
        seat=seat,
        event="seat.activate",
        value="DENY",
        actor=actor,
        actor_role=_primary_role(roles),
        decision_id=decision_id,
    )
    await _seat_event(
        conn,
        org_id=org_id,
        seat=seat,
        seat_version=seat_version,
        from_state="APPROVED",
        to_state="APPROVED",
        actor=actor,
        decision_id=decision_id,
        note=rule,
    )
    await audit_store.record(
        conn,
        org_id=org_id,
        actor=actor,
        action="seat.activate.denied",
        subject=f"{seat}@{seat_version}",
        data={"seat": seat, "seat_version": seat_version, "rule": rule, "decision_id": decision_id},
    )
    return CommittedRefusal(code, 403, title, detail, decision_id, rule=rule)


async def activate_seat(
    conn: AsyncConnection,
    *,
    org: OrgModel,
    org_id: str,
    name: str,
    seat_version: int,
    expected_version: int,
    actor: str,
    roles: list[str],
    eval_strict: bool = False,
) -> dict[str, Any] | CommittedRefusal:
    row = await _lock_seat_row(conn, org_id, name, seat_version)
    if row is None:
        raise SeatError("not_found", 404, "Seat not found", f"No seat {name!r} version {seat_version}.")
    if row[9] != expected_version:
        raise SeatError(
            "stale_version",
            409,
            "Seat changed since you loaded it",
            "Reload the seat and try again.",
            current_version=row[9],
        )
    if row[6] != "APPROVED":
        raise SeatError(
            "conflict",
            409,
            "Seat is not approved",
            f"Activation requires APPROVED; this seat is {row[6]!r}.",
        )
    if eval_strict:
        await _require_eval_no_deferred(
            conn,
            org_id=org_id,
            seat_name=name,
            seat_version=seat_version,
            pack_version_id=str(row[2]),
        )
    else:
        await _require_eval_passed(
            conn,
            org_id=org_id,
            seat_name=name,
            seat_version=seat_version,
            pack_version_id=str(row[2]),
        )

    configured_by = row[7]
    owner_person_id = row[5]
    if configured_by and actor == configured_by:
        return await _record_activate_denied(
            conn,
            org_id=org_id,
            seat=name,
            seat_version=seat_version,
            actor=actor,
            roles=roles,
            rule=RULE_NOT_CONFIGURER,
            code="segregation_of_duties",
            title="You cannot activate a seat you configured",
            detail="Segregation of duties requires the seat owner to activate it.",
        )
    if actor != owner_person_id:
        return await _record_activate_denied(
            conn,
            org_id=org_id,
            seat=name,
            seat_version=seat_version,
            actor=actor,
            roles=roles,
            rule=RULE_NOT_OWNER,
            code="not_permitted",
            title="Only the seat owner may activate",
            detail="Activation is reserved for the person who owns this seat.",
        )

    live = await _find_other_live_seat(conn, org_id, name, seat_version)
    if live is not None:
        live_version, live_state = int(live[0]), live[1]
        raise SeatError(
            "conflict",
            409,
            "Another seat version is already live",
            f"Seat {name!r} version {live_version} is {live_state!r}; "
            f"retire it before activating version {seat_version}.",
        )

    from_state = row[6]
    decision_id = ids.new_decision_id()
    new_record_version = row[9] + 1
    try:
        cur = await conn.execute(
            "update registry.seats set state = 'ACTIVE', activated_by = %s, record_version = %s, updated_at = now()"
            " where org_id = %s and name = %s and version = %s and record_version = %s"
            " returning name, version, pack_version_id, display_name, placement, owner_person_id, state,"
            " configured_by, activated_by, record_version, updated_at",
            (actor, new_record_version, org_id, name, seat_version, expected_version),
        )
        updated = await cur.fetchone()
    except UniqueViolation as exc:
        raise SeatError(
            "conflict",
            409,
            "Another seat version is already live",
            f"Retire the other live version of {name!r} before activating version {seat_version}.",
        ) from exc
    if updated is None:
        raise SeatError(
            "stale_version",
            409,
            "Seat changed since you loaded it",
            "Reload the seat and try again.",
            current_version=row[9],
        )
    await _insert_decision(
        conn,
        org_id=org_id,
        seat=name,
        event="seat.activate",
        value="ALLOW",
        actor=actor,
        actor_role=_primary_role(roles),
        decision_id=decision_id,
    )
    await _seat_event(
        conn,
        org_id=org_id,
        seat=name,
        seat_version=seat_version,
        from_state=from_state,
        to_state="ACTIVE",
        actor=actor,
        decision_id=decision_id,
    )
    await audit_store.record(
        conn,
        org_id=org_id,
        actor=actor,
        action="seat.activated",
        subject=f"{name}@{seat_version}",
        data={"seat": name, "seat_version": seat_version, "decision_id": decision_id},
    )
    await _emit_state_changed(
        conn,
        org,
        seat=name,
        from_state=from_state,
        to_state="ACTIVE",
        owner_person_id=owner_person_id,
        placement=row[4],
    )
    return await project_seat_detail(conn, org_id, updated)
