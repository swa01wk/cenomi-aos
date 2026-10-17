"""M0 routes: persona sign-in, the organization, domain packs and the audit chain."""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from ..kernel import audit_store, instances, publish, registry_store, seats
from ..kernel.publish import PublishRefusal
from ..kernel.refusal import CommittedRefusal
from ..kernel.seats import SeatError
from .problems import KernelProblem, problem_response
from ..kernel.auth import issue_session
from ..registry import validate_pack
from .deps import ConsoleDep, KernelDep, Principal, PrincipalDep, TxDep, needs_role

router = APIRouter()
PackEditor = Annotated[Principal, Depends(needs_role("platform_admin", "process_owner", "seat_owner"))]
Auditor = Annotated[Principal, Depends(needs_role("platform_admin", "risk"))]


def _raise_publish_refusal(exc: PublishRefusal) -> None:
    raise KernelProblem(exc.code, exc.status, exc.title, exc.detail) from exc


def _raise_seat_error(exc: SeatError) -> None:
    raise KernelProblem(exc.code, exc.status, exc.title, exc.detail, **exc.extra) from exc


def _raise_instance_error(exc: instances.InstanceError) -> None:
    raise KernelProblem(exc.code, exc.status, exc.title, exc.detail, **exc.extra) from exc


def _refusal_response(request: Request, refusal: CommittedRefusal):
    extra = {"decision_id": refusal.decision_id}
    if refusal.rule:
        extra["rule"] = refusal.rule
    return problem_response(
        request,
        KernelProblem(refusal.code, refusal.status, refusal.title, refusal.detail, **extra),
    )


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
        )
    except SeatError as exc:
        _raise_seat_error(exc)
    if isinstance(result, CommittedRefusal):
        return _refusal_response(request, result)
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


# ------------------------------------------------------------------ workspace / instances (M1-BE-04 A)

class StartInstanceBody(BaseModel):
    seat: str
    workflow: str
    first_message: str = Field(max_length=4000)


class PostTurnBody(BaseModel):
    text: str = Field(max_length=4000)
    client_turn_id: str


@router.get("/workspace/digital-workers", tags=["workspace"])
async def list_digital_workers(p: PrincipalDep, k: KernelDep, conn: TxDep) -> dict:
    items = await instances.list_digital_workers(conn, k.org, p.org_id, p.person_id, p.roles)
    return {"items": items}


@router.get("/instances", tags=["instances"])
async def list_my_instances(
    p: PrincipalDep,
    k: KernelDep,
    conn: TxDep,
    participant: Annotated[Literal["me"], Query()],
    status: Annotated[Literal["active", "waiting_on_me", "closed"] | None, Query()] = None,
) -> dict:
    items = await instances.list_my_instances(conn, k.org, p.org_id, p.person_id, status=status)
    return {"items": items}


@router.post("/instances", tags=["instances"], status_code=201)
async def start_instance(
    request: Request,
    p: PrincipalDep,
    k: KernelDep,
    conn: TxDep,
    body: StartInstanceBody,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
    try:
        result = await instances.start_instance(
            conn,
            k.org,
            org_id=p.org_id,
            actor=p.person_id,
            roles=p.roles,
            seat_name=body.seat,
            workflow_name=body.workflow,
            first_message=body.first_message,
            idempotency_key=idempotency_key,
            packs_dir=k.settings.packs_dir,
        )
    except instances.InstanceError as exc:
        _raise_instance_error(exc)
    if isinstance(result, CommittedRefusal):
        return _refusal_response(request, result)
    return result


@router.get("/instances/{id}", tags=["instances"])
async def get_instance(id: str, p: PrincipalDep, k: KernelDep, conn: TxDep) -> dict:
    try:
        return await instances.build_snapshot(conn, k.org, p.org_id, id, p.person_id)
    except instances.InstanceError as exc:
        _raise_instance_error(exc)


@router.get("/instances/{id}/turns", tags=["instances"])
async def list_turns(
    id: str,
    p: PrincipalDep,
    k: KernelDep,
    conn: TxDep,
    before_seq: int | None = None,
    limit: Annotated[int, Query(le=100)] = 50,
) -> dict:
    try:
        items = await instances.list_turns_page(
            conn, k.org, p.org_id, id, p.person_id, before_seq=before_seq, limit=limit
        )
    except instances.InstanceError as exc:
        _raise_instance_error(exc)
    return {"items": items}


@router.post("/instances/{id}/turns", tags=["instances"], status_code=202)
async def post_turn(
    id: str,
    request: Request,
    p: PrincipalDep,
    k: KernelDep,
    conn: TxDep,
    body: PostTurnBody,
):
    try:
        result = await instances.post_turn(
            conn,
            k.org,
            org_id=p.org_id,
            instance_id=id,
            actor=p.person_id,
            roles=p.roles,
            text=body.text,
            client_turn_id=body.client_turn_id,
            packs_dir=k.settings.packs_dir,
        )
    except instances.InstanceError as exc:
        _raise_instance_error(exc)
    if isinstance(result, CommittedRefusal):
        return _refusal_response(request, result)
    return result


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
