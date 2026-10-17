"""Persona sessions for the POC (SSO is deferred).

Signing in as a seeded person issues a session token with their org, person id and roles. The
kernel resolves participant roles on an instance server-side; the token never carries them.
"""

from __future__ import annotations

import time

import jwt

from .org import CONSOLE_ROLES, OrgModel

ALGORITHM = "HS256"
SESSION_TTL_S = 8 * 3600


class AuthError(Exception):
    pass


def issue_session(org: OrgModel, person_id: str, secret: str, clock=time.time) -> str:
    person = org.people.get(person_id)
    if person is None:
        raise AuthError(f"no such person {person_id!r}")
    now = int(clock())
    claims = {"iss": "aos-kernel", "aud": WEB_AUD, "sub": person_id, "org": org.organization.id,
              "roles": person.roles, "console": person.console, "iat": now, "exp": now + SESSION_TTL_S}
    return jwt.encode(claims, secret, algorithm=ALGORITHM)


WORKER_AUD = "aos-worker"
WEB_AUD = "aos-web"


def read_session(token: str, secret: str) -> dict:
    try:
        return jwt.decode(token, secret, algorithms=[ALGORITHM], audience=WEB_AUD)
    except jwt.PyJWTError as exc:
        raise AuthError(str(exc)) from exc


def issue_worker_token(org_id: str, worker_id: str, secret: str, clock=time.time) -> str:
    now = int(clock())
    claims = {
        "iss": "aos-kernel",
        "aud": WORKER_AUD,
        "sub": worker_id,
        "org": org_id,
        "iat": now,
        "exp": now + SESSION_TTL_S,
    }
    return jwt.encode(claims, secret, algorithm=ALGORITHM)


def read_worker_token(token: str, secret: str) -> dict:
    try:
        return jwt.decode(token, secret, algorithms=[ALGORITHM], audience=WORKER_AUD)
    except jwt.PyJWTError as exc:
        raise AuthError(str(exc)) from exc


def require_console(claims: dict) -> None:
    if not claims.get("console") or not CONSOLE_ROLES & set(claims.get("roles", [])):
        raise AuthError("Console access needs a Console role")
