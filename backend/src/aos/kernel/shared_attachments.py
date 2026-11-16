"""Shared RFQ attachments (one upload, included on every outbound RFQ for the job)."""

from __future__ import annotations

import re
from typing import Any

from psycopg import AsyncConnection

from . import ids
from .instances import _participant_roles

MAX_BYTES = 2 * 1024 * 1024
_ALLOWED_STATES = frozenset({"rfq_drafting", "rfq_sending", "rfp_invitation_drafting", "rfp_sending"})


class SharedAttachmentError(Exception):
    def __init__(self, code: str, status: int, title: str, detail: str) -> None:
        self.code = code
        self.status = status
        self.title = title
        self.detail = detail
        super().__init__(detail)


def _safe_filename(name: str) -> str:
    base = name.replace("\\", "/").split("/")[-1].strip()
    base = re.sub(r"[^\w.\- ()]", "_", base)
    if not base or base in (".", ".."):
        raise SharedAttachmentError("validation_failed", 422, "Invalid file name", "Choose a file with a valid name.")
    return base[:200]


async def list_for_snapshot(conn: AsyncConnection, *, org_id: str, instance_id: str) -> list[dict[str, Any]]:
    cur = await conn.execute(
        "select id, filename, content_type, size_bytes, uploaded_at"
        " from work.instance_shared_attachments"
        " where org_id = %s and instance_id = %s"
        " order by uploaded_at, id",
        (org_id, instance_id),
    )
    out: list[dict[str, Any]] = []
    for row in await cur.fetchall():
        out.append(
            {
                "attachment_id": row[0],
                "filename": row[1],
                "content_type": row[2],
                "size_bytes": int(row[3]),
                "uploaded_at": row[4].isoformat().replace("+00:00", "Z") if row[4] else "",
            }
        )
    return out


async def filenames_for_instance(conn: AsyncConnection, instance_id: str) -> list[str]:
    cur = await conn.execute(
        "select filename from work.instance_shared_attachments where instance_id = %s order by uploaded_at, id",
        (instance_id,),
    )
    return [str(r[0]) for r in await cur.fetchall()]


async def _require_buyer_upload(
    conn: AsyncConnection,
    *,
    org_id: str,
    instance_id: str,
    person_id: str,
) -> None:
    roles = await _participant_roles(conn, instance_id, person_id)
    if "buyer" not in roles:
        raise SharedAttachmentError(
            "not_permitted",
            403,
            "Not allowed",
            "Only the buyer on this job can manage shared RFQ attachments.",
        )
    cur = await conn.execute(
        "select state, status from work.instances where id = %s and org_id = %s",
        (instance_id, org_id),
    )
    row = await cur.fetchone()
    if row is None:
        raise SharedAttachmentError("not_found", 404, "Job not found", f"No instance {instance_id!r}.")
    state, status = str(row[0]), str(row[1])
    if status != "running":
        raise SharedAttachmentError("conflict", 409, "Job not active", "This job is not running.")
    if state not in _ALLOWED_STATES:
        raise SharedAttachmentError(
            "conflict",
            409,
            "Not at RFQ stage",
            "Shared attachments can be added while RFQ drafts are open or before quotes arrive.",
        )


async def upload(
    conn: AsyncConnection,
    *,
    org_id: str,
    instance_id: str,
    person_id: str,
    filename: str,
    content_type: str,
    data: bytes,
) -> dict[str, Any]:
    await _require_buyer_upload(conn, org_id=org_id, instance_id=instance_id, person_id=person_id)
    if not data:
        raise SharedAttachmentError("validation_failed", 422, "Empty file", "Choose a non-empty file.")
    if len(data) > MAX_BYTES:
        raise SharedAttachmentError(
            "validation_failed",
            422,
            "File too large",
            f"Each attachment must be {MAX_BYTES // (1024 * 1024)} MB or smaller.",
        )
    safe_name = _safe_filename(filename)
    ctype = (content_type or "application/octet-stream").split(";")[0].strip()[:200]
    att_id = ids.new_artifact_id()
    await conn.execute(
        "insert into work.instance_shared_attachments"
        " (id, org_id, instance_id, filename, content_type, size_bytes, content, uploaded_by)"
        " values (%s, %s, %s, %s, %s, %s, %s, %s)",
        (att_id, org_id, instance_id, safe_name, ctype, len(data), data, person_id),
    )
    cur = await conn.execute(
        "select uploaded_at from work.instance_shared_attachments where id = %s",
        (att_id,),
    )
    at_row = await cur.fetchone()
    uploaded_at = at_row[0].isoformat().replace("+00:00", "Z") if at_row and at_row[0] else ""
    return {
        "attachment_id": att_id,
        "filename": safe_name,
        "content_type": ctype,
        "size_bytes": len(data),
        "uploaded_at": uploaded_at,
    }


async def delete_attachment(
    conn: AsyncConnection,
    *,
    org_id: str,
    instance_id: str,
    person_id: str,
    attachment_id: str,
) -> None:
    await _require_buyer_upload(conn, org_id=org_id, instance_id=instance_id, person_id=person_id)
    cur = await conn.execute(
        "delete from work.instance_shared_attachments"
        " where id = %s and org_id = %s and instance_id = %s"
        " returning id",
        (attachment_id, org_id, instance_id),
    )
    if await cur.fetchone() is None:
        raise SharedAttachmentError("not_found", 404, "Attachment not found", "That file is not on this job.")
