"""M0 routes: persona sign-in, the organization, domain packs and the audit chain."""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..evals.runner import run_suite
from ..kernel import (
    artifacts,
    audit_store,
    clock,
    decisions,
    demo,
    instances,
    participants,
    publish,
    registry_store,
    seats,
    timers,
    worker_attempts,
    worker_events,
    worker_questions,
    worker_submit,
    worker_tools,
)
from ..kernel.worker_fence import CommittedFenced, WorkerFenceError, require_claimed_attempt
from ..kernel.publish import PublishRefusal
from ..kernel.refusal import CommittedRefusal
from ..kernel.registry_store import pack_root
from ..kernel.seats import EvalRunJob, SeatError
from ..kernel.simulate import run_simulation_rolled_back
from .problems import KernelProblem, problem_response
from ..kernel.auth import issue_session
from ..registry import validate_pack
from ..sse import InstanceStreamError, instance_event_stream, preflight_instance_stream
from .deps import ConsoleDep, FencingDep, HubDep, Kernel, KernelDep, Principal, PrincipalDep, TxDep, WorkerDep, needs_role

router = APIRouter()
PackEditor = Annotated[Principal, Depends(needs_role("platform_admin", "process_owner", "seat_owner"))]
Auditor = Annotated[Principal, Depends(needs_role("platform_admin", "risk"))]


def _raise_publish_refusal(exc: PublishRefusal) -> None:
    raise KernelProblem(exc.code, exc.status, exc.title, exc.detail) from exc


def _raise_seat_error(exc: SeatError) -> None:
    raise KernelProblem(exc.code, exc.status, exc.title, exc.detail, **exc.extra) from exc


def _raise_instance_error(exc: instances.InstanceError) -> None:
    raise KernelProblem(exc.code, exc.status, exc.title, exc.detail, **exc.extra) from exc


def _raise_artifact_error(exc: artifacts.ArtifactError) -> None:
    raise KernelProblem(exc.code, exc.status, exc.title, exc.detail, **exc.extra) from exc


def _raise_decision_error(exc: decisions.DecisionError) -> None:
    raise KernelProblem(exc.code, exc.status, exc.title, exc.detail, **exc.extra) from exc


def _raise_participant_error(exc: participants.ParticipantError) -> None:
    raise KernelProblem(exc.code, exc.status, exc.title, exc.detail, **exc.extra) from exc


def _fenced_response(request: Request, _fenced: CommittedFenced):
    return problem_response(
        request,
        KernelProblem(
            "fenced",
            409,
            "This attempt is no longer active",
            "The fencing token is stale. Stop without further effects.",
        ),
    )


def _raise_worker_error(exc: worker_attempts.WorkerError) -> None:
    raise KernelProblem(exc.code, exc.status, exc.title, exc.detail, **exc.extra) from exc


def _raise_worker_fence_error(exc: WorkerFenceError) -> None:
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


class SimulatePackRequest(BaseModel):
    workflow: str
    script: str = "dry_run_script"


@router.post("/console/pack-versions/{version_id}/simulate", tags=["registry"])
async def simulate_pack_version(
    version_id: str,
    p: ConsoleDep,
    k: KernelDep,
    body: SimulatePackRequest,
) -> dict:
    async with k.pool.connection() as conn:
        if await registry_store.get_version(conn, p.org_id, version_id) is None:
            raise HTTPException(404, "no such pack version")
    return await run_simulation_rolled_back(
        k.pool,
        k.org,
        org_id=p.org_id,
        pack_version_id=version_id,
        workflow_name=body.workflow,
        script_name=body.script,
        packs_dir=k.settings.packs_dir,
    )


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
    # A Literal gives the same enum in the OpenAPI schema; Query(enum=...) is rejected by current FastAPI.
    status: Annotated[Literal["open", "approved", "rejected"] | None, Query()] = None,
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


@router.get("/instances/{id}/events", tags=["instances"])
async def stream_instance_events(
    request: Request,
    id: str,
    p: PrincipalDep,
    k: KernelDep,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
    cursor: str | None = None,
) -> StreamingResponse:
    try:
        await preflight_instance_stream(k.pool, org_id=p.org_id, instance_id=id, person_id=p.person_id)
    except InstanceStreamError as exc:
        _raise_instance_error(
            instances.InstanceError(exc.code, exc.status, exc.title, exc.detail)
        )
    hub = request.app.state.hub
    resume = last_event_id or cursor
    return StreamingResponse(
        instance_event_stream(
            hub,
            k.pool,
            org_id=p.org_id,
            instance_id=id,
            person_id=p.person_id,
            cursor=resume,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ------------------------------------------------------------------ artifacts (M1-BE-04 C)

@router.get("/artifacts/{id}", tags=["artifacts"])
async def get_artifact(id: str, p: PrincipalDep, k: KernelDep, conn: TxDep) -> dict:
    try:
        return await artifacts.get_artifact(conn, k.org, p.org_id, id, p.person_id)
    except artifacts.ArtifactError as exc:
        _raise_artifact_error(exc)


@router.get("/artifacts/{id}/versions/{version}", tags=["artifacts"])
async def get_artifact_version(
    id: str, version: int, p: PrincipalDep, k: KernelDep, conn: TxDep
) -> dict:
    try:
        return await artifacts.get_artifact_version(conn, k.org, p.org_id, id, version, p.person_id)
    except artifacts.ArtifactError as exc:
        _raise_artifact_error(exc)


class CreateArtifactVersionBody(BaseModel):
    base_version: int
    content: dict[str, Any]


@router.post("/artifacts/{id}/versions", tags=["artifacts"], status_code=201)
async def create_artifact_version(
    id: str,
    p: PrincipalDep,
    k: KernelDep,
    conn: TxDep,
    body: CreateArtifactVersionBody,
) -> dict:
    try:
        return await artifacts.create_artifact_version(
            conn,
            k.org,
            p.org_id,
            id,
            p.person_id,
            body.model_dump(),
            packs_dir=k.settings.packs_dir,
        )
    except artifacts.ArtifactError as exc:
        _raise_artifact_error(exc)


class ClaimInstanceBody(BaseModel):
    role: str
    expected_version: int


@router.get("/queues/{queue:path}/instances", tags=["decisions"])
async def list_queue(queue: str, p: PrincipalDep, k: KernelDep, conn: TxDep) -> dict:
    try:
        items = await participants.list_queue_instances(
            conn, k.org, p.org_id, p.person_id, queue
        )
    except participants.ParticipantError as exc:
        _raise_participant_error(exc)
    return {"items": items}


@router.post("/instances/{id}/claim", tags=["decisions"])
async def claim_instance(
    id: str,
    p: PrincipalDep,
    k: KernelDep,
    conn: TxDep,
    body: ClaimInstanceBody,
) -> dict:
    try:
        return await participants.claim_instance(
            conn,
            k.org,
            p.org_id,
            p.person_id,
            id,
            body.role,
            body.expected_version,
            packs_dir=k.settings.packs_dir,
        )
    except participants.ParticipantError as exc:
        _raise_participant_error(exc)


class DecidePendingBody(BaseModel):
    value: str
    expected_version: int
    artifact_version: int | None = None
    selection: list[str] | None = None
    note: str | None = None


@router.post("/pending/{id}/decide", tags=["decisions"])
async def decide_pending(
    id: str,
    p: PrincipalDep,
    k: KernelDep,
    conn: TxDep,
    body: DecidePendingBody,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict:
    try:
        return await decisions.decide_pending(
            conn,
            k.org,
            p.org_id,
            id,
            p.person_id,
            body.model_dump(),
            idempotency_key=idempotency_key,
            packs_dir=k.settings.packs_dir,
        )
    except decisions.DecisionError as exc:
        _raise_decision_error(exc)


# ------------------------------------------------------------------ worker protocol (M1-BE-05-A)


class ClaimAttemptBody(BaseModel):
    worker_id: str
    lanes: list[Literal["assist", "task"]]


class FailAttemptBody(BaseModel):
    failure_class: Literal["model_error", "tool_timeout", "invalid_output", "budget_exhausted", "internal"]
    message: str = Field(max_length=2000)


class AssembleContextBody(BaseModel):
    reason: Literal["start", "resume", "tool_result", "input_changed", "policy_changed", "explicit"]


@router.post("/worker/attempts/claim", tags=["worker"])
async def claim_attempt(
    w: WorkerDep,
    k: KernelDep,
    conn: TxDep,
    body: ClaimAttemptBody,
):
    if body.worker_id != w.worker_id:
        raise KernelProblem(
            "not_permitted",
            403,
            "Worker id mismatch",
            "The worker_id in the body must match the token subject.",
        )
    try:
        attempt = await worker_attempts.claim_next_attempt(
            conn,
            org_id=w.org_id,
            worker_id=w.worker_id,
            lanes=list(body.lanes),
            lease_seconds=k.settings.worker_lease_seconds,
        )
    except WorkerFenceError as exc:
        _raise_worker_fence_error(exc)
    if attempt is None:
        return Response(status_code=204)
    return attempt


@router.post("/worker/attempts/{id}/heartbeat", tags=["worker"])
async def heartbeat_attempt(
    id: str,
    request: Request,
    w: WorkerDep,
    k: KernelDep,
    conn: TxDep,
    token: FencingDep,
):
    try:
        result = await worker_attempts.heartbeat(
            conn,
            org_id=w.org_id,
            attempt_id=id,
            worker_id=w.worker_id,
            fencing_token=token,
            lease_seconds=k.settings.worker_lease_seconds,
        )
    except WorkerFenceError as exc:
        _raise_worker_fence_error(exc)
    if isinstance(result, CommittedFenced):
        return _fenced_response(request, result)
    return result


@router.get("/worker/attempts/{id}/contract", tags=["worker"])
async def get_attempt_contract(
    id: str,
    request: Request,
    w: WorkerDep,
    k: KernelDep,
    conn: TxDep,
    token: FencingDep,
):
    try:
        result = await worker_attempts.get_contract(
            conn,
            org_id=w.org_id,
            attempt_id=id,
            worker_id=w.worker_id,
            fencing_token=token,
            packs_dir=k.settings.packs_dir,
        )
    except worker_attempts.WorkerError as exc:
        _raise_worker_error(exc)
    except WorkerFenceError as exc:
        _raise_worker_fence_error(exc)
    if isinstance(result, CommittedFenced):
        return _fenced_response(request, result)
    return result


@router.post("/worker/attempts/{id}/context", tags=["worker"])
async def assemble_context_route(
    id: str,
    request: Request,
    w: WorkerDep,
    k: KernelDep,
    conn: TxDep,
    token: FencingDep,
    body: AssembleContextBody,
):
    try:
        result = await worker_attempts.assemble_context(
            conn,
            org_id=w.org_id,
            attempt_id=id,
            worker_id=w.worker_id,
            fencing_token=token,
            refresh_reason=body.reason,
            packs_dir=k.settings.packs_dir,
            org=k.org,
        )
    except WorkerFenceError as exc:
        _raise_worker_fence_error(exc)
    except worker_attempts.WorkerError as exc:
        _raise_worker_error(exc)
    if isinstance(result, CommittedFenced):
        return _fenced_response(request, result)
    if isinstance(result, CommittedRefusal):
        return _refusal_response(request, result)
    return result


class CallToolBody(BaseModel):
    args: dict[str, Any] = Field(default_factory=dict)


@router.post("/worker/attempts/{id}/tools/{tool}", tags=["worker"])
async def call_tool_route(
    id: str,
    tool: str,
    request: Request,
    w: WorkerDep,
    k: KernelDep,
    token: FencingDep,
    body: CallToolBody,
):
    try:
        result = await worker_tools.call_tool(
            k.pool,
            org_id=w.org_id,
            attempt_id=id,
            worker_id=w.worker_id,
            fencing_token=token,
            tool=tool,
            args=body.args,
            broker=k.broker,
            gateway=k.gateway,
        )
    except worker_attempts.WorkerError as exc:
        _raise_worker_error(exc)
    except WorkerFenceError as exc:
        _raise_worker_fence_error(exc)
    if isinstance(result, CommittedRefusal):
        return _refusal_response(request, result)
    if isinstance(result, CommittedFenced):
        return _fenced_response(request, result)
    if isinstance(result, worker_tools.CommittedConnectorFailure):
        title = "Connector call failed"
        detail = result.detail
        return problem_response(
            request,
            KernelProblem(
                "connector_failed",
                502,
                title,
                detail,
                timed_out=result.timed_out,
            ),
        )
    return result


@router.post("/worker/attempts/{id}/fail", tags=["worker"])
async def fail_attempt_route(
    id: str,
    request: Request,
    w: WorkerDep,
    k: KernelDep,
    conn: TxDep,
    token: FencingDep,
    body: FailAttemptBody,
):
    try:
        result = await worker_attempts.fail_attempt(
            conn,
            org=k.org,
            org_id=w.org_id,
            attempt_id=id,
            worker_id=w.worker_id,
            fencing_token=token,
            failure_class=body.failure_class,
            message=body.message,
        )
    except WorkerFenceError as exc:
        _raise_worker_fence_error(exc)
    if not result.ended and result.fenced is not None:
        return _fenced_response(request, result.fenced)
    return {"recorded": True}


class PostAttemptEventsBody(BaseModel):
    events: list[dict[str, Any]] | None = None
    stream: list[dict[str, Any]] | None = None


class AskQuestionsBody(BaseModel):
    blocks: list[dict[str, Any]]
    questions: list[str] | None = None


@router.post("/worker/attempts/{id}/events", tags=["worker"], status_code=202)
async def post_attempt_events_route(
    id: str,
    request: Request,
    w: WorkerDep,
    conn: TxDep,
    token: FencingDep,
    hub: HubDep,
    body: PostAttemptEventsBody,
):
    try:
        result = await worker_events.post_attempt_events(
            conn,
            org_id=w.org_id,
            attempt_id=id,
            worker_id=w.worker_id,
            fencing_token=token,
            events=body.events,
            stream=body.stream,
            hub=hub,
            org=request.app.state.kernel.org,
        )
    except worker_attempts.WorkerError as exc:
        _raise_worker_error(exc)
    except WorkerFenceError as exc:
        _raise_worker_fence_error(exc)
    if isinstance(result, CommittedFenced):
        return _fenced_response(request, result)
    if isinstance(result, worker_attempts.EndAttemptResult) and result.fenced is not None:
        return _fenced_response(request, result.fenced)
    return Response(status_code=202)


@router.post("/worker/attempts/{id}/drafts", tags=["worker"], status_code=201)
async def save_draft_route(
    id: str,
    request: Request,
    w: WorkerDep,
    k: KernelDep,
    conn: TxDep,
    token: FencingDep,
    body: dict[str, Any],
):
    try:
        gate = await require_claimed_attempt(
            conn, org_id=w.org_id, attempt_id=id, worker_id=w.worker_id, fencing_token=token
        )
    except WorkerFenceError as exc:
        _raise_worker_fence_error(exc)
    if isinstance(gate, CommittedFenced):
        return _fenced_response(request, gate)
    from ..kernel.instances import _load_definitions

    pvid = await conn.execute(
        "select pack_version_id from work.instances where id = %s",
        (gate.instance_id,),
    )
    row = await pvid.fetchone()
    defs = await _load_definitions(conn, str(row[0])) if row else {}
    try:
        return await artifacts.save_draft_from_attempt(
            conn, org=k.org, gate=gate, body=body, defs=defs, packs_dir=k.settings.packs_dir
        )
    except artifacts.ArtifactError as exc:
        _raise_artifact_error(exc)


@router.post("/worker/attempts/{id}/questions", tags=["worker"], status_code=201)
async def ask_questions_route(
    id: str,
    request: Request,
    w: WorkerDep,
    conn: TxDep,
    token: FencingDep,
    body: AskQuestionsBody,
):
    try:
        result = await worker_questions.ask_questions(
            conn,
            org_id=w.org_id,
            attempt_id=id,
            worker_id=w.worker_id,
            fencing_token=token,
            blocks=body.blocks,
            questions=body.questions,
        )
    except WorkerFenceError as exc:
        _raise_worker_fence_error(exc)
    if isinstance(result, CommittedFenced):
        return _fenced_response(request, result)
    return result


@router.post("/worker/attempts/{id}/submit", tags=["worker"])
async def submit_result_route(
    id: str,
    request: Request,
    w: WorkerDep,
    k: KernelDep,
    conn: TxDep,
    token: FencingDep,
    body: dict[str, Any],
):
    try:
        result = await worker_submit.submit_result(
            conn,
            org=k.org,
            org_id=w.org_id,
            attempt_id=id,
            worker_id=w.worker_id,
            fencing_token=token,
            result=body,
            packs_dir=k.settings.packs_dir,
        )
    except worker_attempts.WorkerError as exc:
        _raise_worker_error(exc)
    except WorkerFenceError as exc:
        _raise_worker_fence_error(exc)
    if isinstance(result, CommittedFenced):
        return _fenced_response(request, result)
    return result


# ------------------------------------------------------------------ demo (sandbox)

def _require_demo(k: KernelDep) -> None:
    if not k.settings.demo:
        raise HTTPException(404, "Not found")


class AdvanceClockMinutes(BaseModel):
    minutes: int = Field(ge=1)


class AdvanceClockNextTimer(BaseModel):
    to_next_timer: Literal[True]


@router.get("/demo/state", tags=["demo"])
async def get_demo_state(k: KernelDep, p: ConsoleDep, conn: TxDep) -> dict:
    _require_demo(k)
    return await demo.build_demo_state(conn, p.org_id)


@router.post("/demo/clock/advance", tags=["demo"])
async def advance_clock(
    k: KernelDep,
    p: ConsoleDep,
    body: AdvanceClockMinutes | AdvanceClockNextTimer,
) -> dict:
    _require_demo(k)
    minutes = body.minutes if isinstance(body, AdvanceClockMinutes) else None
    to_next = isinstance(body, AdvanceClockNextTimer)
    async with k.pool.connection() as conn:
        async with conn.transaction():
            offset = await demo.advance_demo_clock(
                conn,
                p.org_id,
                minutes=minutes,
                to_next_timer=to_next,
            )
    clock.set_offset(offset)
    await timers.run_timer_tick(
        k.pool,
        as_of=clock.now(),
        org=k.org,
        packs_dir=k.settings.packs_dir,
    )
    async with k.pool.connection() as conn:
        return await demo.build_demo_state(conn, p.org_id)


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
