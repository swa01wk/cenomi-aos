"""Credential broker: short-lived, single-action tokens for connector calls.

The worker never holds a credential. For each allowed or approved action the gateway asks the
broker for a token naming exactly one resource and action; the connector verifies it. Keys
rotate on a kill, which revokes every outstanding token at once.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

import jwt

ALGORITHM = "HS256"
DEFAULT_TTL_S = 60
ISSUER = "aos-broker"


class TokenRejected(Exception):
    pass


@dataclass(frozen=True)
class Grant:
    connector: str
    resource: str
    action: str
    action_id: str
    org_id: str
    tool: str
    attempt_id: str


class CredentialBroker:
    def __init__(self, secrets: dict[str, str], ttl_s: int = DEFAULT_TTL_S, clock=time.time):
        self._secrets = dict(secrets)  # connector -> shared secret (never given to the worker)
        self._ttl = ttl_s
        self._clock = clock
        self._generation = 0

    def mint(self, grant: Grant) -> str:
        secret = self._secrets.get(grant.connector)
        if secret is None:
            raise KeyError(f"no service identity for connector {grant.connector!r}")
        now = int(self._clock())
        claims = {
            "iss": ISSUER,
            "aud": grant.connector,
            "sub": grant.action_id,
            "jti": uuid.uuid4().hex,
            "iat": now,
            "exp": now + self._ttl,
            "org": grant.org_id,
            "res": grant.resource,
            "act": grant.action,
            "tool": grant.tool,
            "att": grant.attempt_id,
            "gen": self._generation,
        }
        return jwt.encode(claims, secret, algorithm=ALGORITHM)

    def rotate(self, new_secrets: dict[str, str]) -> None:
        """Called by emergency control: every token minted before this is now invalid."""
        self._secrets = dict(new_secrets)
        self._generation += 1


def verify_token(
    token: str,
    *,
    secret: str,
    connector: str,
    resource: str,
    action: str,
    tool: str | None = None,
    clock=time.time,
) -> dict:
    """Used by a connector. Raises TokenRejected unless the token allows exactly this resource and action."""
    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=[ALGORITHM],
            audience=connector,
            options={"verify_exp": False, "require": ["exp", "aud", "sub", "res", "act", "tool", "att"]},
            leeway=0,
        )
    except jwt.PyJWTError as exc:
        raise TokenRejected(f"invalid token: {exc}") from exc
    if claims["exp"] < int(clock()):
        raise TokenRejected("token expired")
    if claims["res"] != resource or claims["act"] != action:
        raise TokenRejected(f"token is for {claims['res']}.{claims['act']}, not {resource}.{action}")
    if tool is not None and claims.get("tool") != tool:
        raise TokenRejected(f"token is for tool {claims.get('tool')!r}, not {tool!r}")
    return claims
