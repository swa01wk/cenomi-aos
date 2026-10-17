"""Signing for inbound events from connectors to the kernel (HMAC-SHA256 over the exact body)."""

from __future__ import annotations

import hashlib
import hmac
import json

HEADER = "X-AOS-Signature"


def canonical(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()


def sign(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def verify(body: bytes, signature: str | None, secret: str) -> bool:
    if not signature:
        return False
    return hmac.compare_digest(sign(body, secret), signature)
