"""Readable identifiers for kernel-owned rows."""

from __future__ import annotations

import re
import secrets
from uuid import UUID, uuid4

from psycopg import AsyncConnection

from ..registry.kinds import WorkflowSpec

# WorkflowDefinition.spec.id_prefix (pack schema); see WorkflowSpec in registry/kinds.py.
_INSTANCE_PREFIX_PATTERN = WorkflowSpec.model_json_schema()["properties"]["id_prefix"]["pattern"]
INSTANCE_PREFIX_RE = re.compile(_INSTANCE_PREFIX_PATTERN)

AGGREGATE_SEQ_STREAM_PREFIX = "run:"
OUTBOX_STREAM_PREFIXES = ("instance:", "user:")

# Contract: docs/specs/contracts/README.md (Kernel identifiers). Examples/ use narrative demo ids.
_SUFFIX_BYTES = 8


def validate_instance_prefix(prefix: str) -> str:
    if not INSTANCE_PREFIX_RE.fullmatch(prefix):
        raise ValueError(
            f"instance id_prefix must match WorkflowSpec.id_prefix ({_INSTANCE_PREFIX_PATTERN}): {prefix!r}"
        )
    return prefix


def format_instance_id(prefix: str, n: int) -> str:
    """Format ``<prefix>-<n>`` with at least four digits; never truncate larger numbers."""
    validate_instance_prefix(prefix)
    if n < 1:
        raise ValueError("instance number must be >= 1")
    width = max(4, len(str(n)))
    return f"{prefix}-{n:0{width}d}"


async def next_instance_id(conn: AsyncConnection, prefix: str) -> str:
    validate_instance_prefix(prefix)
    cur = await conn.execute("select nextval('work.instance_number')")
    row = await cur.fetchone()
    if row is None:
        raise RuntimeError("work.instance_number returned no row")
    return format_instance_id(prefix, int(row[0]))


def _new_prefixed_id(label: str) -> str:
    return f"{label}{secrets.token_hex(_SUFFIX_BYTES)}"


def new_task_id() -> str:
    return _new_prefixed_id("task_")


def new_attempt_id() -> str:
    return _new_prefixed_id("att_")


def new_turn_id() -> str:
    return _new_prefixed_id("turn_")


def new_artifact_id() -> str:
    return _new_prefixed_id("art_")


def new_pending_id() -> str:
    return _new_prefixed_id("pend_")


def new_decision_id() -> str:
    return _new_prefixed_id("dr_")


def new_contract_id() -> str:
    return _new_prefixed_id("tc_")


def new_envelope_id() -> str:
    return _new_prefixed_id("ce_")


def new_eval_run_id() -> str:
    return _new_prefixed_id("ev_")


def is_outbox_stream(stream: str) -> bool:
    return stream.startswith(OUTBOX_STREAM_PREFIXES)


def stream_instance(instance_id: str) -> str:
    return f"instance:{instance_id}"


def stream_user(person_id: str) -> str:
    return f"user:{person_id}"


def aggregate_seq_stream(run_id: str) -> str:
    """Internal ``stream_heads`` key for ``aggregate_seq``; never an outbox or SSE stream."""
    return f"{AGGREGATE_SEQ_STREAM_PREFIX}{run_id}"


def ui_event_cursor(stream: str, seq: int) -> str:
    return f"{stream}:{seq}"


def parse_ui_event_cursor(cursor: str) -> tuple[str, int]:
    """Split ``<stream>:<seq>`` on the last colon (stream names contain ``:``)."""
    if not cursor or ":" not in cursor:
        raise ValueError("cursor must be '<stream>:<seq>'")
    stream, seq_s = cursor.rsplit(":", 1)
    if not stream or not seq_s.isdigit():
        raise ValueError("cursor must be '<stream>:<seq>'")
    seq = int(seq_s)
    if seq < 0:
        raise ValueError("cursor seq must be >= 0")
    return stream, seq


def new_event_id() -> UUID:
    return uuid4()
