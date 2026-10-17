"""The audit hash chain (ADR 008).

Each organization has one append-only chain. A record's hash covers the previous record's hash
and the record's canonical JSON, so changing, inserting or deleting any record breaks every
hash after it, and ``verify`` names the first broken record.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone

GENESIS = "0" * 64


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class AuditRecord:
    org_id: str
    seq: int
    occurred_at: str
    actor: str
    action: str
    subject: str
    correlation_id: str | None = None
    data: dict = field(default_factory=dict)
    prev_hash: str = GENESIS
    record_hash: str = ""

    def canonical(self) -> str:
        body = {k: v for k, v in asdict(self).items() if k not in ("prev_hash", "record_hash")}
        return json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)

    def compute_hash(self) -> str:
        return hashlib.sha256(f"{self.prev_hash}\n{self.canonical()}".encode()).hexdigest()


def append(head_seq: int, head_hash: str, *, org_id: str, actor: str, action: str, subject: str,
           correlation_id: str | None = None, data: dict | None = None, occurred_at: str | None = None) -> AuditRecord:
    """Build the next record on a chain whose head is (head_seq, head_hash). The caller holds the head lock."""
    rec = AuditRecord(org_id=org_id, seq=head_seq + 1, occurred_at=occurred_at or utcnow(), actor=actor,
                      action=action, subject=subject, correlation_id=correlation_id, data=data or {},
                      prev_hash=head_hash)
    return replace(rec, record_hash=rec.compute_hash())


@dataclass(frozen=True)
class ChainReport:
    intact: bool
    records: int
    head_hash: str
    first_broken_seq: int | None = None
    reason: str = ""


def verify(records: list[AuditRecord]) -> ChainReport:
    """Walk a chain in seq order; return the first record whose link or hash does not hold."""
    prev, expected_seq = GENESIS, 1
    for rec in sorted(records, key=lambda r: r.seq):
        if rec.seq != expected_seq:
            return ChainReport(False, len(records), prev, expected_seq, f"missing record {expected_seq}")
        if rec.prev_hash != prev:
            return ChainReport(False, len(records), prev, rec.seq, "previous-hash link broken")
        if rec.compute_hash() != rec.record_hash:
            return ChainReport(False, len(records), prev, rec.seq, "record content changed")
        prev, expected_seq = rec.record_hash, expected_seq + 1
    return ChainReport(True, len(records), prev)
