"""Publish requests: open, approve, reject and complete a pack version (M1-BE-02)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from . import audit_store


@dataclass(frozen=True)
class PublishRefusal(Exception):
    code: str
    status: int
    title: str
    detail: str = ""

PART_POLICIES = "policies"
PART_SEATS = "seats_and_workflows"
ROLE_RISK = "risk"
ROLE_OWNER = "owner"


def _part_key(entry: dict[str, Any]) -> str:
    return str(entry.get("for") or entry.get("part"))


def _build_required_approvers(*, has_policy: bool, pack_owner: str) -> list[dict[str, Any]]:
    required: list[dict[str, Any]] = []
    if has_policy:
        required.append({"for": PART_POLICIES, "role": ROLE_RISK})
    required.append({"for": PART_SEATS, "role": ROLE_OWNER, "person_id": pack_owner})
    return required


def _parts_view(required: list[dict[str, Any]], approvals: list[dict[str, Any]], *, request_status: str) -> list[dict]:
    by_part = {a["part"]: a for a in approvals if "part" in a}
    out: list[dict] = []
    for req in required:
        part = _part_key(req)
        role = req["role"]
        if request_status == "rejected":
            ap = by_part.get(part)
            if ap and ap.get("rejected"):
                st = "rejected"
                by, at = ap.get("by"), ap.get("at")
            else:
                st = "rejected"
                by, at = None, None
        else:
            ap = by_part.get(part)
            if ap and ap.get("rejected"):
                st = "rejected"
                by, at = ap.get("by"), ap.get("at")
            elif ap:
                st = "approved"
                by, at = ap.get("by"), ap.get("at")
            else:
                st = "open"
                by, at = None, None
        row: dict[str, Any] = {"part": part, "role": role, "status": st, "by": by, "at": at}
        out.append(row)
    return out


def _row_to_publish_request(row: tuple) -> dict[str, Any]:
    rid, pvid, requested_by, requested_at, status, required, approvals = row
    required_list = required if isinstance(required, list) else json.loads(required)
    approvals_list = approvals if isinstance(approvals, list) else json.loads(approvals)
    return {
        "id": str(rid),
        "pack_version_id": str(pvid),
        "status": status,
        "requested_by": requested_by,
        "requested_at": requested_at.isoformat(),
        "parts": _parts_view(required_list, approvals_list, request_status=status),
    }


async def _has_policy_definitions(conn: AsyncConnection, pack_version_id: str) -> bool:
    cur = await conn.execute(
        "select exists(select 1 from registry.definitions where pack_version_id = %s and kind = 'Policy')",
        (pack_version_id,),
    )
    row = await cur.fetchone()
    return bool(row and row[0])


async def _lock_version(conn: AsyncConnection, org_id: str, version_id: str) -> tuple[str, str, str, str | None]:
    cur = await conn.execute(
        "select v.id, v.status, v.pack_name, p.owner"
        " from registry.pack_versions v"
        " join registry.packs p on p.org_id = v.org_id and p.name = v.pack_name"
        " where v.org_id = %s and v.id = %s"
        " for update of v",
        (org_id, version_id),
    )
    row = await cur.fetchone()
    if row is None:
        raise PublishRefusal("not_found", 404, "Pack version not found", "No such pack version in this organization.")
    return str(row[0]), row[1], row[2], row[3]


async def _lock_request_for_version(
    conn: AsyncConnection, org_id: str, version_id: str
) -> dict[str, Any] | None:
    cur = await conn.execute(
        "select pr.id, pr.pack_version_id, pr.requested_by, pr.requested_at, pr.status,"
        " pr.required_approvers, pr.approvals"
        " from registry.publish_requests pr"
        " join registry.pack_versions v on v.id = pr.pack_version_id"
        " where v.org_id = %s and pr.pack_version_id = %s and pr.status = 'open'"
        " for update of pr",
        (org_id, version_id),
    )
    row = await cur.fetchone()
    return _row_to_publish_request(row) if row else None


async def _lock_request_by_id(conn: AsyncConnection, org_id: str, request_id: str) -> tuple[dict[str, Any], str, str]:
    cur = await conn.execute(
        "select v.id, v.status, v.pack_name"
        " from registry.publish_requests pr"
        " join registry.pack_versions v on v.id = pr.pack_version_id"
        " where pr.id = %s and v.org_id = %s"
        " for update of v",
        (request_id, org_id),
    )
    vrow = await cur.fetchone()
    if vrow is None:
        raise PublishRefusal(
            "not_found", 404, "Publish request not found", "No such publish request in this organization."
        )
    version_id, version_status, pack_name = str(vrow[0]), vrow[1], vrow[2]

    cur = await conn.execute(
        "select pr.id, pr.pack_version_id, pr.requested_by, pr.requested_at, pr.status,"
        " pr.required_approvers, pr.approvals"
        " from registry.publish_requests pr"
        " where pr.id = %s"
        " for update of pr",
        (request_id,),
    )
    row = await cur.fetchone()
    if row is None:
        raise PublishRefusal("not_found", 404, "Publish request not found", "No such publish request.")
    return _row_to_publish_request(row), version_id, version_status


def _caller_may_approve_part(
    *,
    part: str,
    required: list[dict[str, Any]],
    person_id: str,
    roles: list[str],
) -> bool:
    entry = next((r for r in required if _part_key(r) == part), None)
    if entry is None:
        return False
    if part == PART_POLICIES:
        return ROLE_RISK in roles
    if part == PART_SEATS:
        return person_id == entry.get("person_id")
    return False


def _open_entitled_parts(
    *, required: list[dict[str, Any]], approvals: list[dict[str, Any]], person_id: str, roles: list[str]
) -> list[str]:
    approved_parts = {a["part"] for a in approvals if a.get("part") and not a.get("rejected")}
    parts: list[str] = []
    for req in required:
        part = _part_key(req)
        if part in approved_parts:
            continue
        if _caller_may_approve_part(part=part, required=required, person_id=person_id, roles=roles):
            parts.append(part)
    return parts


def _all_parts_approved(required: list[dict[str, Any]], approvals: list[dict[str, Any]]) -> bool:
    approved = {a["part"] for a in approvals if a.get("part") and not a.get("rejected")}
    return all(_part_key(r) in approved for r in required)


async def _complete_publish(
    conn: AsyncConnection,
    *,
    org_id: str,
    version_id: str,
    pack_name: str,
    actor: str,
    request_id: str,
) -> None:
    # M1-BE-03 will insert registry.seats rows here when a pack version is published.
    cur = await conn.execute(
        "update registry.pack_versions"
        " set status = 'published', published_at = coalesce(published_at, now())"
        " where id = %s and org_id = %s and status <> 'published'"
        " returning published_at",
        (version_id, org_id),
    )
    row = await cur.fetchone()
    if row is not None:
        await audit_store.record(
            conn,
            org_id=org_id,
            actor=actor,
            action="pack.published",
            subject=f"{pack_name}@{version_id}",
            data={"pack_version_id": version_id, "publish_request_id": request_id},
        )
    await conn.execute(
        "update registry.publish_requests set status = 'approved' where id = %s",
        (request_id,),
    )


async def request_publish(
    conn: AsyncConnection,
    *,
    org_id: str,
    version_id: str,
    requester: str,
) -> tuple[dict[str, Any], bool]:
    """Open a publish request. Returns (body, created). created is False when returning an existing open request."""
    vid, status, _pack_name, pack_owner = await _lock_version(conn, org_id, version_id)
    existing = await _lock_request_for_version(conn, org_id, vid)
    if existing is not None:
        if existing["requested_by"] == requester:
            return existing, False
        raise PublishRefusal(
            "conflict",
            409,
            "Publish request already open",
            "Another person already opened a publish request for this version.",
        )

    if status != "validated":
        raise PublishRefusal(
            "validation_failed",
            422,
            "Version is not ready to publish",
            f"The pack version status is {status!r}; it must be validated.",
        )

    has_policy = await _has_policy_definitions(conn, vid)
    required = _build_required_approvers(has_policy=has_policy, pack_owner=pack_owner)
    if any(_part_key(r) == PART_SEATS for r in required) and requester == pack_owner:
        raise PublishRefusal(
            "segregation_of_duties",
            403,
            "You cannot request publish for your own pack",
            "The pack owner must not be the requester, because the owner must approve Seats and workflows.",
        )

    cur = await conn.execute(
        "insert into registry.publish_requests"
        " (pack_version_id, requested_by, status, required_approvers, approvals)"
        " values (%s, %s, 'open', %s, '[]'::jsonb)"
        " returning id, pack_version_id, requested_by, requested_at, status, required_approvers, approvals",
        (vid, requester, Jsonb(required)),
    )
    row = await cur.fetchone()
    await conn.execute(
        "update registry.pack_versions set status = 'publish_requested' where id = %s and org_id = %s",
        (vid, org_id),
    )
    await audit_store.record(
        conn,
        org_id=org_id,
        actor=requester,
        action="pack.publish_requested",
        subject=f"{_pack_name}@{vid}",
        data={"pack_version_id": vid, "publish_request_id": str(row[0])},
    )
    return _row_to_publish_request(row), True


async def list_publish_requests(
    conn: AsyncConnection,
    *,
    org_id: str,
    status: str | None = None,
) -> list[dict[str, Any]]:
    sql = (
        "select pr.id, pr.pack_version_id, pr.requested_by, pr.requested_at, pr.status,"
        " pr.required_approvers, pr.approvals"
        " from registry.publish_requests pr"
        " join registry.pack_versions v on v.id = pr.pack_version_id"
        " where v.org_id = %s"
    )
    params: list[Any] = [org_id]
    if status is not None:
        sql += " and pr.status = %s"
        params.append(status)
    sql += " order by pr.requested_at desc"
    cur = await conn.execute(sql, params)
    return [_row_to_publish_request(r) for r in await cur.fetchall()]


async def approve_publish_part(
    conn: AsyncConnection,
    *,
    org_id: str,
    request_id: str,
    part: str,
    actor: str,
    roles: list[str],
    note: str | None = None,
) -> dict[str, Any]:
    body, version_id, version_status = await _lock_request_by_id(conn, org_id, request_id)
    if version_status == "published":
        return body

    if body["status"] != "open":
        raise PublishRefusal(
            "conflict",
            409,
            "Publish request is closed",
            "This publish request is no longer open.",
        )

    if actor == body["requested_by"]:
        raise PublishRefusal(
            "segregation_of_duties",
            403,
            "The requester cannot approve",
            "The person who requested publish cannot approve any part of it.",
        )

    cur = await conn.execute(
        "select required_approvers, approvals from registry.publish_requests where id = %s",
        (request_id,),
    )
    row = await cur.fetchone()
    required = row[0] if isinstance(row[0], list) else json.loads(row[0])
    approvals = list(row[1] if isinstance(row[1], list) else json.loads(row[1]))

    if not _caller_may_approve_part(part=part, required=required, person_id=actor, roles=roles):
        raise PublishRefusal(
            "not_permitted",
            403,
            "Not the approver for this part",
            f"You are not required to approve the {part!r} part.",
        )

    if any(a.get("part") == part and not a.get("rejected") for a in approvals):
        merged = body
    else:
        cur = await conn.execute(
            "select pack_name from registry.pack_versions where id = %s",
            (version_id,),
        )
        pack_name = (await cur.fetchone())[0]
        entry: dict[str, Any] = {
            "part": part,
            "by": actor,
            "at": datetime.now(timezone.utc).isoformat(),
        }
        if note:
            entry["note"] = note
        approvals.append(entry)
        await conn.execute(
            "update registry.publish_requests set approvals = %s where id = %s",
            (Jsonb(approvals), request_id),
        )
        await audit_store.record(
            conn,
            org_id=org_id,
            actor=actor,
            action="pack.publish_part_approved",
            subject=f"{pack_name}@{version_id}",
            data={"pack_version_id": version_id, "publish_request_id": request_id, "part": part},
        )
        if _all_parts_approved(required, approvals):
            await _complete_publish(
                conn,
                org_id=org_id,
                version_id=version_id,
                pack_name=pack_name,
                actor=actor,
                request_id=request_id,
            )
        body, _, _ = await _lock_request_by_id(conn, org_id, request_id)
        merged = body
    return merged


async def reject_publish(
    conn: AsyncConnection,
    *,
    org_id: str,
    request_id: str,
    actor: str,
    roles: list[str],
    reason: str,
) -> dict[str, Any]:
    body, version_id, version_status = await _lock_request_by_id(conn, org_id, request_id)
    if body["status"] != "open":
        raise PublishRefusal(
            "conflict",
            409,
            "Publish request is closed",
            "This publish request is no longer open.",
        )

    if actor == body["requested_by"]:
        raise PublishRefusal(
            "segregation_of_duties",
            403,
            "The requester cannot reject",
            "The person who requested publish cannot reject any part of it.",
        )

    cur = await conn.execute(
        "select required_approvers, approvals from registry.publish_requests where id = %s",
        (request_id,),
    )
    row = await cur.fetchone()
    required = row[0] if isinstance(row[0], list) else json.loads(row[0])
    approvals = list(row[1] if isinstance(row[1], list) else json.loads(row[1]))

    reject_parts = _open_entitled_parts(
        required=required, approvals=approvals, person_id=actor, roles=roles
    )
    if not reject_parts:
        raise PublishRefusal(
            "not_permitted",
            403,
            "Not a required approver",
            "Only a required approver for an open part may reject this request.",
        )

    cur = await conn.execute("select pack_name from registry.pack_versions where id = %s", (version_id,))
    pack_name = (await cur.fetchone())[0]

    at = datetime.now(timezone.utc).isoformat()
    for part in reject_parts:
        approvals.append({"part": part, "by": actor, "at": at, "rejected": True})

    await conn.execute(
        "update registry.publish_requests set status = 'rejected', approvals = %s where id = %s",
        (Jsonb(approvals), request_id),
    )
    await conn.execute(
        "update registry.pack_versions set status = 'validated' where id = %s and org_id = %s",
        (version_id, org_id),
    )
    await audit_store.record(
        conn,
        org_id=org_id,
        actor=actor,
        action="pack.publish_rejected",
        subject=f"{pack_name}@{version_id}",
        data={
            "pack_version_id": version_id,
            "publish_request_id": request_id,
            "reason": reason,
            "part": reject_parts[0] if len(reject_parts) == 1 else reject_parts,
        },
    )
    body, _, _ = await _lock_request_by_id(conn, org_id, request_id)
    return body


def parse_request_id(raw: str) -> UUID:
    try:
        return UUID(raw)
    except ValueError as exc:
        raise PublishRefusal(
            "not_found", 404, "Publish request not found", "The id is not a valid publish request id."
        ) from exc


def parse_version_id(raw: str) -> UUID:
    try:
        return UUID(raw)
    except ValueError as exc:
        raise PublishRefusal(
            "not_found", 404, "Pack version not found", "The version id is not a valid pack version id."
        ) from exc
