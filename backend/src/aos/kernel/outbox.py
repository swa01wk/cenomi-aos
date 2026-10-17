"""Transactional outbox, execution-event writer and in-transaction NOTIFY (ADR 013).

Postgres delivers ``pg_notify`` payloads when the surrounding transaction commits and discards
them on rollback, so NOTIFY is issued inside the same transaction as the outbox insert.

Open question: ``run_id`` for execution events that are not tied to a work instance is not defined
in the contract yet; callers must supply an explicit ``run_id`` until the spec does.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from . import ids

OUTBOX_CHANNEL = "aos_outbox"

_ALLOCATE_SEQ_SQL = """
insert into evidence.stream_heads (stream, last_seq)
values (%s, 1)
on conflict (stream) do update
set last_seq = evidence.stream_heads.last_seq + 1
returning last_seq
"""


async def allocate_stream_seq(conn: AsyncConnection, stream: str) -> int:
    cur = await conn.execute(_ALLOCATE_SEQ_SQL, (stream,))
    row = await cur.fetchone()
    if row is None:
        raise RuntimeError(f"stream seq allocation failed for {stream!r}")
    return int(row[0])


async def notify_stream(conn: AsyncConnection, stream: str) -> None:
    await conn.execute("select pg_notify(%s, %s)", (OUTBOX_CHANNEL, stream))


async def append_outbox(
    conn: AsyncConnection,
    *,
    stream: str,
    event_type: str,
    instance_id: str | None,
    audience: dict[str, Any],
    data: dict[str, Any],
) -> int:
    if not ids.is_outbox_stream(stream):
        raise ValueError(
            f"outbox stream must start with {ids.OUTBOX_STREAM_PREFIXES!r}, not {stream!r} "
            f"({ids.AGGREGATE_SEQ_STREAM_PREFIX}* is reserved for aggregate_seq counters)"
        )
    seq = await allocate_stream_seq(conn, stream)
    await conn.execute(
        "insert into evidence.outbox (stream, seq, event_type, instance_id, audience, data)"
        " values (%s, %s, %s, %s, %s, %s)",
        (stream, seq, event_type, instance_id, Jsonb(audience), Jsonb(data)),
    )
    await notify_stream(conn, stream)
    return seq


@dataclass(frozen=True)
class ExecutionEventWrite:
    org_id: str
    run_id: str
    event_type: str
    actor_kind: str
    actor_id: str
    correlation_id: str
    redacted_summary: str
    task_id: str | None = None
    attempt_id: str | None = None
    causation_id: UUID | None = None
    contract_version: int | None = None
    graph_revision: str | None = None
    artifact_refs: list[str] | None = None
    payload_ref: str | None = None
    attributes: dict[str, Any] | None = None
    event_id: UUID | None = None


async def write_execution_event(conn: AsyncConnection, event: ExecutionEventWrite) -> UUID:
    aggregate_seq = await allocate_stream_seq(conn, ids.aggregate_seq_stream(event.run_id))
    event_id = event.event_id or ids.new_event_id()
    await conn.execute(
        "insert into evidence.execution_events ("
        " event_id, org_id, run_id, aggregate_seq, event_type, task_id, attempt_id,"
        " actor_kind, actor_id, correlation_id, causation_id, contract_version, graph_revision,"
        " artifact_refs, payload_ref, redacted_summary, attributes"
        ") values ("
        " %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s"
        ")",
        (
            event_id,
            event.org_id,
            event.run_id,
            aggregate_seq,
            event.event_type,
            event.task_id,
            event.attempt_id,
            event.actor_kind,
            event.actor_id,
            event.correlation_id,
            event.causation_id,
            event.contract_version,
            event.graph_revision,
            event.artifact_refs or [],
            event.payload_ref,
            event.redacted_summary,
            Jsonb(event.attributes or {}),
        ),
    )
    return event_id


def execution_event_document(
    event_id: UUID,
    *,
    org_id: str,
    run_id: str,
    aggregate_seq: int,
    event_type: str,
    actor_kind: str,
    actor_id: str,
    correlation_id: str,
    redacted_summary: str,
    occurred_at: str,
    task_id: str | None = None,
    attempt_id: str | None = None,
    causation_id: UUID | None = None,
    contract_version: int | None = None,
    graph_revision: str | None = None,
    artifact_refs: list[str] | None = None,
    payload_ref: str | None = None,
    attributes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the JSON shape of ``execution-event.schema.json`` (``tenant_id`` is org_id)."""
    doc: dict[str, Any] = {
        "event_id": str(event_id),
        "schema_version": "aos.execution_event/1",
        "event_type": event_type,
        "occurred_at": occurred_at,
        "tenant_id": org_id,
        "run_id": run_id,
        "actor": {"kind": actor_kind, "id": actor_id},
        "correlation_id": correlation_id,
        "aggregate_seq": aggregate_seq,
        "redacted_summary": redacted_summary,
        "artifact_refs": artifact_refs or [],
    }
    if task_id is not None:
        doc["task_id"] = task_id
    if attempt_id is not None:
        doc["attempt_id"] = attempt_id
    if causation_id is not None:
        doc["causation_id"] = str(causation_id)
    if contract_version is not None:
        doc["contract_version"] = contract_version
    if graph_revision is not None:
        doc["graph_revision"] = graph_revision
    if payload_ref is not None:
        doc["payload_ref"] = payload_ref
    if attributes:
        doc["attributes"] = attributes
    return doc
