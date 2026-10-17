"""Request dependencies: the kernel state, a database transaction and the signed-in person."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request
from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

from ..kernel.auth import AuthError, read_session, read_worker_token, require_console
from ..kernel.org import OrgModel
from ..kernel.settings import Settings


@dataclass
class Kernel:
    settings: Settings
    org: OrgModel
    pool: AsyncConnectionPool


def kernel(request: Request) -> Kernel:
    return request.app.state.kernel


async def tx(k: Annotated[Kernel, Depends(kernel)]) -> AsyncIterator[AsyncConnection]:
    """One transaction per request: the change and its audit record commit together or not at all."""
    async with k.pool.connection() as conn:
        async with conn.transaction():
            yield conn


@dataclass(frozen=True)
class Principal:
    person_id: str
    org_id: str
    roles: list[str]
    console: bool


def _bearer_token(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "sign in first", headers={"WWW-Authenticate": "Bearer"})
    return authorization[7:]


def principal(k: Annotated[Kernel, Depends(kernel)],
              authorization: Annotated[str | None, Header()] = None) -> Principal:
    try:
        claims = read_session(_bearer_token(authorization), k.settings.session_secret)
    except AuthError as exc:
        raise HTTPException(401, f"session rejected: {exc}", headers={"WWW-Authenticate": "Bearer"}) from exc
    if claims["org"] != k.org.organization.id or claims["sub"] not in k.org.people:
        raise HTTPException(401, "session is for another organization or a removed person")
    return Principal(claims["sub"], claims["org"], claims.get("roles", []), bool(claims.get("console")))


def console_user(p: Annotated[Principal, Depends(principal)]) -> Principal:
    try:
        require_console({"console": p.console, "roles": p.roles})
    except AuthError as exc:
        raise HTTPException(403, str(exc)) from exc
    return p


def needs_role(*roles: str):
    def check(p: Annotated[Principal, Depends(console_user)]) -> Principal:
        if not set(roles) & set(p.roles):
            raise HTTPException(403, f"needs one of the roles {sorted(roles)}")
        return p
    return check


@dataclass(frozen=True)
class WorkerPrincipal:
    worker_id: str
    org_id: str


def worker_principal(
    k: Annotated[Kernel, Depends(kernel)],
    authorization: Annotated[str | None, Header()] = None,
) -> WorkerPrincipal:
    try:
        claims = read_worker_token(_bearer_token(authorization), k.settings.session_secret)
    except AuthError as exc:
        raise HTTPException(401, f"worker token rejected: {exc}", headers={"WWW-Authenticate": "Bearer"}) from exc
    if claims["org"] != k.org.organization.id:
        raise HTTPException(401, "worker token is for another organization")
    return WorkerPrincipal(claims["sub"], claims["org"])


def fencing_token(
    x_aos_fencing_token: Annotated[int | None, Header(alias="X-AOS-Fencing-Token")] = None,
) -> int:
    if x_aos_fencing_token is None:
        raise HTTPException(422, "X-AOS-Fencing-Token is required")
    return int(x_aos_fencing_token)


KernelDep = Annotated[Kernel, Depends(kernel)]
TxDep = Annotated[AsyncConnection, Depends(tx)]
PrincipalDep = Annotated[Principal, Depends(principal)]
WorkerDep = Annotated[WorkerPrincipal, Depends(worker_principal)]
FencingDep = Annotated[int, Depends(fencing_token)]
ConsoleDep = Annotated[Principal, Depends(console_user)]
