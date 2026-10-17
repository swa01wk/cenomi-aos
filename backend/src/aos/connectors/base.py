"""Shared pieces of the mock connectors: storage, fault switches and token checks."""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass, field

import anyio

from aos.gateway.broker import TokenRejected, verify_token


class ConnectorError(Exception):
    """Raised inside a tool; surfaces to the gateway as an MCP tool error."""

    def __init__(self, kind: str, message: str):
        super().__init__(f"{kind}: {message}")
        self.kind = kind  # permanent | validation | auth | not_found


@dataclass
class Faults:
    """Demo and test fault switches. Never reachable by the agent: only admin tools set them."""

    timeout_after_commit: int = 0       # how many next committed calls stall after committing
    timeout_delay_s: float = 30.0
    fail_validation: int = 0            # how many next committed calls fail validation
    oversized_reads: bool = False

    def take(self, name: str) -> bool:
        left = getattr(self, name)
        if left > 0:
            setattr(self, name, left - 1)
            return True
        return False


class Store:
    """A small SQLite store; ':memory:' in tests, a file in Compose."""

    def __init__(self, path: str, schema: str):
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._db.executescript(schema)

    def q(self, sql: str, args: tuple = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._db.execute(sql, args).fetchall()]

    def one(self, sql: str, args: tuple = ()) -> dict | None:
        rows = self.q(sql, args)
        return rows[0] if rows else None

    def x(self, sql: str, args: tuple = ()) -> int:
        with self._lock:
            return self._db.execute(sql, args).lastrowid


@dataclass
class ConnectorConfig:
    name: str
    secret: str | None = None          # None disables token checks (unit tests of tool logic only)
    db_path: str = ":memory:"
    faults: Faults = field(default_factory=Faults)

    def check(self, token: str | None, resource: str, action: str) -> None:
        if self.secret is None:
            return
        if not token:
            raise ConnectorError("auth", "missing broker token")
        try:
            verify_token(token, secret=self.secret, connector=self.name, resource=resource, action=action)
        except TokenRejected as exc:
            raise ConnectorError("auth", str(exc)) from exc


async def stall(cfg: ConnectorConfig) -> None:
    """The commit already happened; now behave like a network that never answers in time."""
    await anyio.sleep(cfg.faults.timeout_delay_s)


def dumps(obj) -> str:
    return json.dumps(obj, default=str)
