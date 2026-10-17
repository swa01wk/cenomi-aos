"""M0 routes: persona sign-in, the organization, domain packs and the audit chain."""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from ..kernel import audit_store, publish, registry_store, seats
from ..kernel.publish import PublishRefusal
from ..evals.runner import run_suite
from ..kernel.registry_store import pack_root
from ..kernel.seats import CommittedRefusal, EvalRunJob, SeatError
from .problems import KernelProblem, problem_response
from ..kernel.auth import issue_session
from ..registry import validate_pack
from .deps import ConsoleDep, Kernel, KernelDep, Principal, PrincipalDep, TxDep, needs_role

router = APIRouter()
PackEditor = Annotated[Principal, Depends(needs_role("platform_admin", "process_owner", "seat_owner"))]
Auditor = Annotated[Principal, Depends(needs_role("platform_admin", "risk"))]


def _raise_publish_refusal(exc: PublishRefusal) -> None:
    raise KernelProblem(exc.code, exc.status, exc.title, exc.detail) from exc


def _raise_seat_error(exc: SeatError) -> None:
    raise KernelProblem(exc.code, exc.status, exc.title, exc.detail, **exc.extra) from exc


@router.get("/healthz", tags=["ops"])
async def healthz(conn: TxDep) -> dict:
    await conn.execute("select 1")
    return {"status": "ok"}


# ------------------------------------------------------------------ sign-in (POC personas; SSO deferred)

@router.get("/auth/personas", tags=["auth"])
def personas(k: KernelDep) -> list[dict]:
    """The seeded people a demo can sign in as. Replaced by the identity provider after the POC."""
    return [{"id": pid, "name": p.name, "team": p.team, "roles": p.roles, "console": p.console}
            for pid, p in k.org.people.items()]


class SessionRequest(BaseModel):
    person_id: str


@router.post("/auth/session", tags=["auth"])
async def start_session(body: SessionRequest, k: KernelDep, conn: TxDep) -> dict:
    person = k.org.people.get(body.person_id)
    if person is None:
        raise HTTPException(404, f"no such person {body.person_id!r}")
    token = issue_session(k.org, body.person_id, k.settings.session_secret)
    await audit_store.record(conn, org_id=k.org.organization.id, actor=body.person_id, action="session.started",
                             subject=f"person:{body.person_id}", data={"console": person.console})
    return {"token": token, "person": {"id": body.person_id, **person.model_dump()}}


@router.get("/me", tags=["auth"])
def me(p: PrincipalDep, k: KernelDep) -> dict:
    person = k.org.people[p.person_id]
    return {"id": p.person_id, "org": p.org_id, "name": person.name, "team": person.team, "roles": p.roles,
            "console": p.console}


# ------------------------------------------------------------------ organization

@router.get("/org", tags=["org"])
async def organization(p: PrincipalDep, conn: TxDep) -> dict:
    org = await (await conn.execute("select id, name, data_residency from org.organizations where id = %s",
                                    (p.org_id,))).fetchone()
    depts = await (await conn.execute(
        "select id, name, head_person_id from org.departments where org_id = %s order by id", (p.org_id,))).fetchall()
    teams = await (await conn.execute(
        "select department_id, id, name, owner_person_id from org.teams where org_id = %s order by id",
        (p.org_id,))).fetchall()
    people = await (await conn.execute(
        "select p.id, p.name, p.department_id, p.team_id, p.console_access,"
        " coalesce(array_agg(r.role order by r.role) filter (where r.role is not null), '{}')"
        " from org.people p left join org.role_mappings r on r.org_id = p.org_id and r.person_id = p.id"
        " where p.org_id = %s group by p.id, p.name, p.department_id, p.team_id, p.console_access order by p.id",
        (p.org_id,))).fetchall()
    return {
        "organization": {"id": org[0], "name": org[1], "data_residency": org[2]},
        "departments": [{"id": d, "name": n, "head": h,
                         "teams": [{"id": t, "name": tn, "owner": o} for dd, t, tn, o in teams if dd == d]}
                        for d, n, h in depts],
        "people": [{"id": i, "name": n, "department": d, "team": t, "console": c, "roles": list(r)}
                   for i, n, d, t, c, r in people],
    }


# ------------------------------------------------------------------ domain packs (Console)

@router.get("/console/packs", tags=["registry"])
async def packs(p: ConsoleDep, k: KernelDep, conn: TxDep) -> dict:
    stored = await registry_store.list_packs(conn, p.org_id)
    return {"available": registry_store.available_packs(k.settings.packs_dir), "packs": stored}


def _root(k, name: str):
    try:
        return registry_store.pack_root(k.settings.packs_dir, name)
    except registry_store.PackNotFound as exc:
        raise HTTPException(404, f"no pack {name!r} in the packs folder") from exc


@router.post("/console/packs/{name}/validate", tags=["registry"])
def validate(name: str, p: ConsoleDep, k: KernelDep) -> dict:
    """``aos validate`` over HTTP: checks the pack folder; stores nothing."""
    return validate_pack(_root(k, name), org=k.org.as_validation_org()).to_dict()


class SyncRequest(BaseModel):
    source: str = "local"


@router.post("/console/packs/{name}/sync", tags=["registry"])
async def sync(name: str, p: PackEditor, k: KernelDep, conn: TxDep, body: SyncRequest | None = None) -> dict:
    _root(k, name)
    try:
        result = await registry_store.sync_pack(conn, org=k.org, packs_dir=k.settings.packs_dir, name=name,
                                                actor=p.person_id, source=(body or SyncRequest()).source)
    except registry_store.VersionTaken as exc:
        raise HTTPException(409, str(exc)) from exc
    return asdict(result)


@router.get("/console/pack-versions/{version_id}", tags=["registry"])
async def pack_version(version_id: str, p: ConsoleDep, conn: TxDep) -> dict:
    v = await registry_store.get_version(conn, p.org_id, version_id)
    if v is None:
        raise HTTPException(404, "no such pack version")
    return v


@router.get("/console/pack-versions/{version_id}/definitions/{kind}/{name}", tags=["registry"])
async def definition(version_id: str, kind: str, name: str, p: ConsoleDep, conn: TxDep) -> dict:
    if await registry_store.get_version(conn, p.org_id, version_id) is None:
        raise HTTPException(404, "no such pack version")
    spec = await registry_store.get_definition(conn, version_id, kind, name)
    if spec is None:
        raise HTTPException(404, f"no {kind} {name!r} in this version")
    return spec


# ------------------------------------------------------------------ publish requests (Console, M1)

@router.post("/console/pack-versions/{version_id}/publish-requests", tags=["registry"])
async def request_publish(version_id: str, p: PackEditor, conn: TxDep, response: Response) -> dict:
    try:
        publish.parse_version_id(version_id)
        body, created = await publish.request_publish(
            conn, org_id=p.org_id, version_id=version_id, requester=p.person_id
        )
    except PublishRefusal as exc:
        _raise_publish_refusal(exc)
    response.status_code = 201 if created else 200
    return body


@router.get("/console/publish-requests", tags=["registry"])
async def list_publish_requests(
    p: ConsoleDep,
    conn: TxDep,
    status: Annotated[str | None, Query(enum=["open", "approved", "rejected"])] = None,
) -> dict:
    return {"items": await publish.list_publish_requests(conn, org_id=p.org_id, status=status)}


class ApprovePublishPartBody(BaseModel):
    part: Literal["policies", "seats_and_workflows"]
    note: str | None = None


@router.post("/console/publish-requests/{id}/approve", tags=["registry"])
async def approve_publish_part(id: str, p: ConsoleDep, k: KernelDep, conn: TxDep, body: ApprovePublishPartBody) -> dict:
    try:
        publish.parse_request_id(id)
        return await publish.approve_publish_part(
            conn,
            org=k.org,
            org_id=p.org_id,
            request_id=id,
            part=body.part,
            actor=p.person_id,
            roles=p.roles,
            note=body.note,
        )
    except PublishRefusal as exc:
        _raise_publish_refusal(exc)


# ------------------------------------------------------------------ seats (Console, M1)

class SeatLifecycleBody(BaseModel):
    version: int
    expected_version: int


class RunSeatEvalsBody(BaseModel):
    version: int
    model: Literal["fake", "real"] = "fake"


def _eval_error_detail(exc: BaseException) -> dict[str, Any]:
    message = str(exc).strip() or exc.__class__.__name__
    if len(message) > 240:
        message = message[:237] + "..."
    return {"reason": "error", "message": message}


async def _complete_seat_eval_jobs(
    kernel: Kernel,
    *,
    org_id: str,
    seat: str,
    seat_version: int,
    pack_version_id: str,
    pack_name: str,
    jobs: list[EvalRunJob],
) -> None:
    """Run suites outside any request transaction; M1-BE-05 moves this to the worker lane."""
    root = pack_root(kernel.settings.packs_dir, pack_name)
    async with kernel.pool.connection() as conn:
        async with conn.transaction():
            defs = await seats.definitions_for_pack_version(conn, pack_version_id)
            pinned_digest = await seats.pack_version_digest(conn, pack_version_id)
    for job in jobs:
        passed, total, status = 0, 0, "failed"
        result_detail: dict[str, Any] = {}
        try:
            suite_doc = defs.get("EvalSuite", {}).get(job.suite)
            if suite_doc is None:
                result_detail = {
                    "checks": [{"name": "suite_spec", "passed": False, "detail": "missing EvalSuite definition"}],
                    "expectations": [],
                    "deferred_count": 0,
                }
                passed, total, status = 0, 1, "failed"
            else:
                suite_file = None
                async with kernel.pool.connection() as conn:
                    suite_file = await seats.eval_suite_file(conn, pack_version_id, job.suite)
                outcome = run_suite(
                    suite_name=job.suite,
                    suite_spec=suite_doc,
                    defs=defs,
                    pack_root=root,
                    suite_file=suite_file,
                    pinned_digest=pinned_digest,
                )
                passed, total, status = outcome.passed, outcome.total, outcome.status
                result_detail = outcome.detail
        except Exception as exc:  # noqa: BLE001 - record runner failure on the eval run row
            result_detail = _eval_error_detail(exc)
        async with kernel.pool.connection() as conn:
            async with conn.transaction():
                await seats.record_eval_run_result(
                    conn,
                    run_id=job.run_id,
                    passed=passed,
                    total=total,
                    status=status,
                    detail=result_detail,
                )
                if status == "passed":
                    await seats.maybe_promote_seat_to_testing(
                        conn,
                        org=kernel.org,
                        org_id=org_id,
                        name=seat,
                        seat_version=seat_version,
                    )


@router.get("/console/seats", tags=["seats"])
async def list_seats(p: ConsoleDep, conn: TxDep) -> dict:
    return {"items": await seats.list_seats(conn, p.org_id)}


@router.get("/console/seats/{seat}", tags=["seats"])
async def get_seat(seat: str, p: ConsoleDep, conn: TxDep) -> dict:
    try:
        return await seats.get_seat(conn, p.org_id, seat)
    except SeatError as exc:
        _raise_seat_error(exc)


@router.post("/console/seats/{seat}/configure", tags=["seats"])
async def configure_seat(
    seat: str, p: PackEditor, k: KernelDep, conn: TxDep, body: SeatLifecycleBody
) -> dict:
    try:
        return await seats.configure_seat(
            conn,
            org=k.org,
            org_id=p.org_id,
            name=seat,
            seat_version=body.version,
            expected_version=body.expected_version,
            actor=p.person_id,
        )
    except SeatError as exc:
        _raise_seat_error(exc)


@router.post("/console/seats/{seat}/evals", tags=["seats"], status_code=202)
async def run_seat_evals(
    seat: str,
    p: PackEditor,
    k: KernelDep,
    background: BackgroundTasks,
    body: RunSeatEvalsBody,
) -> list[dict]:
    if body.model == "real":
        raise KernelProblem(
            "validation_failed",
            422,
            "Real model evals are not available yet",
            "Use the fake model in M1; real model evals arrive in M4.",
        )
    try:
        async with k.pool.connection() as conn:
            async with conn.transaction():
                pack_version_id, jobs, started = await seats.begin_seat_eval_runs(
                    conn,
                    org_id=p.org_id,
                    name=seat,
                    seat_version=body.version,
                    model=body.model,
                )
                row = await conn.execute(
                    "select pack_name from registry.pack_versions where id = %s and org_id = %s",
                    (pack_version_id, p.org_id),
                )
                pack_row = await row.fetchone()
                pack_name = pack_row[0] if pack_row else ""
    except SeatError as exc:
        _raise_seat_error(exc)
    background.add_task(
        _complete_seat_eval_jobs,
        k,
        org_id=p.org_id,
        seat=seat,
        seat_version=body.version,
        pack_version_id=pack_version_id,
        pack_name=pack_name,
        jobs=jobs,
    )
    return started


@router.post("/console/seats/{seat}/approve", tags=["seats"])
async def approve_seat(
    seat: str, p: ConsoleDep, k: KernelDep, conn: TxDep, body: SeatLifecycleBody
) -> dict:
    try:
        return await seats.approve_seat(
            conn,
            org=k.org,
            org_id=p.org_id,
            name=seat,
            seat_version=body.version,
            expected_version=body.expected_version,
            actor=p.person_id,
            roles=p.roles,
            eval_strict=k.settings.eval_strict,
        )
    except SeatError as exc:
        _raise_seat_error(exc)


@router.post("/console/seats/{seat}/activate", tags=["seats"])
async def activate_seat(
    seat: str, request: Request, p: ConsoleDep, k: KernelDep, conn: TxDep, body: SeatLifecycleBody
):
    try:
        result = await seats.activate_seat(
            conn,
            org=k.org,
            org_id=p.org_id,
            name=seat,
            seat_version=body.version,
            expected_version=body.expected_version,
            actor=p.person_id,
            roles=p.roles,
            eval_strict=k.settings.eval_strict,
        )
    except SeatError as exc:
        _raise_seat_error(exc)
    if isinstance(result, CommittedRefusal):
        extra = {"decision_id": result.decision_id}
        if result.rule:
            extra["rule"] = result.rule
        return problem_response(
            request,
            KernelProblem(result.code, result.status, result.title, result.detail, **extra),
        )
    return result


class RejectPublishBody(BaseModel):
    reason: str = Field(min_length=3)


@router.post("/console/publish-requests/{id}/reject", tags=["registry"])
async def reject_publish(id: str, p: ConsoleDep, conn: TxDep, body: RejectPublishBody) -> dict:
    try:
        publish.parse_request_id(id)
        return await publish.reject_publish(
            conn,
            org_id=p.org_id,
            request_id=id,
            actor=p.person_id,
            roles=p.roles,
            reason=body.reason,
        )
    except PublishRefusal as exc:
        _raise_publish_refusal(exc)


# ------------------------------------------------------------------ audit (Console)

@router.get("/console/audit", tags=["audit"])
async def audit_page(p: Auditor, conn: TxDep, limit: Annotated[int, Query(ge=1, le=500)] = 50,
                     before_seq: int | None = None, correlation_id: str | None = None) -> dict:
    recs = await audit_store.page(conn, p.org_id, limit=limit, before_seq=before_seq, correlation_id=correlation_id)
    return {"items": [asdict(r) for r in recs]}


@router.post("/console/audit/verify", tags=["audit"])
async def audit_verify(p: Auditor, conn: TxDep) -> dict:
    report = await audit_store.verify_chain(conn, p.org_id)
    await audit_store.record(conn, org_id=p.org_id, actor=p.person_id, action="audit.verified", subject="audit-chain",
                             data={"intact": report.intact, "records": report.records,
                                   "first_broken_seq": report.first_broken_seq})
    return asdict(report)
