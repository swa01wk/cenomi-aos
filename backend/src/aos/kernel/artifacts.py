"""Artifact reads and visibility projection (M1-BE-04 C)."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from ..registry.kinds import ArtifactType, ArtifactTypeSpec, FieldSpec
from . import clock, ids
from .contracts import _canonical_json
from .org import OrgModel


async def _participant_roles(conn: AsyncConnection, instance_id: str, person_id: str) -> list[str]:
    cur = await conn.execute(
        "select role from work.participants where instance_id = %s and person_id = %s",
        (instance_id, person_id),
    )
    return [row[0] for row in await cur.fetchall()]

Classification = Literal["shareable", "internal", "restricted"]
_CLASS_RANK = {"shareable": 0, "internal": 1, "restricted": 2}


class ArtifactError(Exception):
    def __init__(self, code: str, status: int, title: str, detail: str = "", **extra: Any) -> None:
        self.code = code
        self.status = status
        self.title = title
        self.detail = detail
        self.extra = extra
        super().__init__(title)


@dataclass(frozen=True)
class VersionRecord:
    artifact_id: str
    artifact_type: str
    version: int
    status: str
    content: dict[str, Any]
    content_hash: str
    produced_by_kind: str
    produced_by: str
    inputs: list[Any]
    sources: list[Any]
    verification: dict[str, Any] | None
    created_at: datetime


def _humanize(name: str) -> str:
    return re.sub(r"\s+", " ", name.replace("_", " ")).strip().title()


def _field_label(name: str, field: FieldSpec) -> str:
    return field.label if field.label else _humanize(name)


def parse_artifact_type(defs: dict[str, dict[str, dict]], type_name: str) -> ArtifactType:
    raw = defs.get("ArtifactType", {}).get(type_name)
    if raw is None:
        raise ArtifactError(
            "internal",
            500,
            "Artifact type missing",
            f"ArtifactType {type_name!r} is not on the pinned pack.",
        )
    return ArtifactType.model_validate(raw)


def _effective_classification(field: FieldSpec, spec: ArtifactTypeSpec) -> Classification:
    return field.classification or spec.classification  # type: ignore[return-value]


def _fields_for_roles(spec: ArtifactTypeSpec, viewer_roles: list[str]) -> set[str]:
    all_names = set(spec.fields.keys())
    allowed: set[str] = set()
    for role in viewer_roles:
        vis = spec.visibility.get(role)
        if vis is None:
            continue
        if vis == "all":
            allowed |= all_names
        elif vis == "none":
            continue
        elif isinstance(vis, list):
            allowed |= {f for f in vis if f in all_names}
        else:
            continue
    return allowed


def _apply_ceiling(names: set[str], spec: ArtifactTypeSpec, ceiling: Classification | None) -> set[str]:
    if ceiling is None:
        return names
    max_rank = _CLASS_RANK[ceiling]
    out: set[str] = set()
    for name in names:
        rank = _CLASS_RANK[_effective_classification(spec.fields[name], spec)]
        if rank <= max_rank:
            out.add(name)
    return out


def _schema_field_names_in_content(content: dict[str, Any], *, row_based: bool, spec: ArtifactTypeSpec) -> set[str]:
    schema_names = set(spec.fields.keys())
    if row_based:
        found: set[str] = set()
        rows = content.get("rows")
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict):
                    found |= {k for k in row if k in schema_names}
        return found
    if not isinstance(content, dict):
        return set()
    return {k for k in content if k in schema_names}


def _filter_content(content: dict[str, Any], *, row_based: bool, allowed: set[str]) -> dict[str, Any]:
    if row_based:
        rows = content.get("rows")
        if not isinstance(rows, list):
            return {"rows": []}
        filtered_rows: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            filtered_rows.append({k: v for k, v in row.items() if k in allowed})
        return {"rows": filtered_rows}
    if not isinstance(content, dict):
        return {}
    return {k: v for k, v in content.items() if k in allowed}


def _sanitize_inputs(inputs: list[Any], *, redacting: bool) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in inputs:
        if not isinstance(item, dict):
            continue
        if redacting:
            ref = {k: item[k] for k in ("artifact_id", "version") if k in item and item[k] is not None}
            if ref:
                out.append(ref)
        else:
            out.append(
                {
                    k: item[k]
                    for k in ("artifact_id", "version", "content_hash")
                    if k in item
                }
            )
    return out


def _sanitize_sources(sources: list[Any], *, redacting: bool) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in sources:
        if not isinstance(item, dict):
            continue
        if redacting:
            ref = {k: item[k] for k in ("source_ref", "label") if k in item and item[k] is not None}
            if ref:
                out.append(ref)
        else:
            out.append({k: item[k] for k in ("source_ref", "label") if k in item})
    return out


def _sanitize_verification(verification: dict[str, Any] | None, *, redacting: bool) -> dict[str, Any] | None:
    if verification is None:
        return None
    if not redacting:
        return verification
    slim: dict[str, Any] = {}
    if "verifier" in verification:
        slim["verifier"] = verification["verifier"]
    if "verdict" in verification:
        slim["verdict"] = verification["verdict"]
    return slim or None


def redaction_reason_for_field(
    field_name: str,
    type_spec: ArtifactTypeSpec,
    viewer_roles: list[str],
    *,
    classification_ceiling: Classification | None = None,
) -> Literal["visibility", "classification"]:
    role_fields = _fields_for_roles(type_spec, viewer_roles)
    if field_name not in role_fields:
        return "visibility"
    if classification_ceiling is not None:
        eff = _effective_classification(type_spec.fields[field_name], type_spec)
        if _CLASS_RANK[eff] > _CLASS_RANK[classification_ceiling]:
            return "classification"
    return "visibility"


def artifact_redaction_entries(
    projected: dict[str, Any],
    type_spec: ArtifactTypeSpec,
    viewer_roles: list[str],
    *,
    classification_ceiling: Classification | None = None,
) -> list[dict[str, Any]]:
    hidden = projected.get("hidden_fields") or []
    if not hidden:
        return []
    artifact_id = projected["artifact_id"]
    artifact_type = projected["artifact_type"]
    return [
        {
            "artifact_type": artifact_type,
            "artifact_id": artifact_id,
            "field": name,
            "reason": redaction_reason_for_field(
                name, type_spec, viewer_roles, classification_ceiling=classification_ceiling
            ),
        }
        for name in hidden
    ]


def envelope_content_hash(projected: dict[str, Any]) -> str:
    if "projected_content_hash" in projected:
        return str(projected["projected_content_hash"])
    return str(projected["content_hash"])


def envelope_artifact_item(projected: dict[str, Any], *, status: str, key: str = "") -> dict[str, Any]:
    item = {
        "artifact_type": projected["artifact_type"],
        "artifact_id": projected["artifact_id"],
        "version": int(projected["version"]),
        "content_hash": envelope_content_hash(projected),
        "status": status,
        "content": projected["content"],
    }
    if key:
        item["key"] = key
    return item


_ENVELOPE_ARTIFACT_STATUSES = frozenset({"draft", "final", "locked"})


def envelope_artifact_status(raw: str) -> str:
    if raw not in _ENVELOPE_ARTIFACT_STATUSES:
        raise ArtifactError(
            "internal",
            500,
            "Unknown artifact status",
            f"Artifact status {raw!r} cannot be placed in a context envelope.",
        )
    return raw


async def artifacts_for_types(
    conn: AsyncConnection,
    instance_id: str,
    artifact_types: set[str],
) -> list[tuple[str, str, str, str, int]]:
    """Return (id, artifact_type, key, status, latest_version) rows ordered by type and key."""
    if not artifact_types:
        return []
    cur = await conn.execute(
        "select id, artifact_type, key, status, latest_version from work.artifacts"
        " where instance_id = %s and artifact_type = any(%s)"
        " order by artifact_type, key",
        (instance_id, list(artifact_types)),
    )
    return [(r[0], r[1], r[2], r[3], int(r[4])) for r in await cur.fetchall()]


async def artifact_instance_id(conn: AsyncConnection, artifact_id: str) -> str | None:
    cur = await conn.execute("select instance_id from work.artifacts where id = %s", (artifact_id,))
    row = await cur.fetchone()
    return str(row[0]) if row else None


def project(
    version: VersionRecord,
    type_spec: ArtifactTypeSpec,
    viewer_roles: list[str],
    *,
    classification_ceiling: Classification | None = None,
    latest_version: int | None = None,
) -> dict[str, Any]:
    """Drop fields the viewer may not see; list removed schema field names in ``hidden_fields``."""
    all_type_fields = set(type_spec.fields.keys())
    allowed = _apply_ceiling(_fields_for_roles(type_spec, viewer_roles), type_spec, classification_ceiling)
    projected_content = _filter_content(version.content, row_based=type_spec.row_based, allowed=allowed)
    present = _schema_field_names_in_content(version.content, row_based=type_spec.row_based, spec=type_spec)
    projected_names = _schema_field_names_in_content(projected_content, row_based=type_spec.row_based, spec=type_spec)
    hidden_fields = sorted(present - projected_names)
    redacting = allowed != all_type_fields

    body: dict[str, Any] = {
        "artifact_id": version.artifact_id,
        "artifact_type": version.artifact_type,
        "version": version.version,
        "content": projected_content,
        "hidden_fields": hidden_fields,
        "produced_by": {
            "kind": version.produced_by_kind,
            "id": version.produced_by,
        },
        "created_at": version.created_at.isoformat()
        if hasattr(version.created_at, "isoformat")
        else str(version.created_at),
    }
    if latest_version is not None and version.version == latest_version:
        body["status"] = version.status
    if redacting:
        body["projected_content_hash"] = hashlib.sha256(_canonical_json(projected_content)).hexdigest()
    else:
        body["content_hash"] = version.content_hash

    inputs = _sanitize_inputs(version.inputs if isinstance(version.inputs, list) else [], redacting=redacting)
    if inputs:
        body["inputs"] = inputs
    sources = _sanitize_sources(version.sources if isinstance(version.sources, list) else [], redacting=redacting)
    if sources:
        body["sources"] = sources
    verification = _sanitize_verification(version.verification, redacting=redacting)
    if verification is not None:
        body["verification"] = verification
    return body


def build_artifact_view(type_spec: ArtifactTypeSpec, allowed: set[str]) -> dict[str, Any]:
    view = type_spec.view
    columns = [c for c in (view.columns or []) if c in allowed]
    fields = [
        {
            "name": name,
            "label": _field_label(name, type_spec.fields[name]),
            "type": type_spec.fields[name].type,
        }
        for name in type_spec.fields
        if name in allowed
    ]
    out: dict[str, Any] = {"type": view.type, "fields": fields}
    if columns:
        out["columns"] = columns
    if view.export is not None:
        out["export"] = view.export
    return out


def _produced_by_name(org: OrgModel, kind: str, producer_id: str, seat_names: dict[str, str] | None = None) -> str:
    """A person's name, or for an attempt the display name of the Seat that ran it (falls back to the id)."""
    if kind == "person" and producer_id in org.people:
        return org.people[producer_id].name
    if kind == "attempt" and seat_names and producer_id in seat_names:
        return seat_names[producer_id]
    return producer_id


async def _attempt_seat_names(conn: AsyncConnection, attempt_ids: list[str]) -> dict[str, str]:
    """attempt id → display name of the Seat whose job it ran in."""
    if not attempt_ids:
        return {}
    cur = await conn.execute(
        "select a.id, s.display_name from work.attempts a"
        " join work.tasks t on t.id = a.task_id"
        " join work.instances i on i.id = t.instance_id"
        " join registry.seats s on s.org_id = i.org_id and s.name = i.seat and s.version = i.seat_version"
        " where a.id = any(%s)",
        (attempt_ids,),
    )
    return {str(aid): str(name) for aid, name in await cur.fetchall()}


async def _artifact_context(
    conn: AsyncConnection,
    org_id: str,
    artifact_id: str,
    person_id: str,
) -> tuple[Any, ...]:
    cur = await conn.execute(
        "select a.id, a.instance_id, a.artifact_type, a.name, a.status, a.latest_version,"
        " i.pack_version_id"
        " from work.artifacts a"
        " join work.instances i on i.id = a.instance_id and i.org_id = %s"
        " where a.id = %s",
        (org_id, artifact_id),
    )
    row = await cur.fetchone()
    if row is None:
        raise ArtifactError("not_found", 404, "Artifact not found", f"No artifact {artifact_id!r}.")
    instance_id = row[1]
    roles = await _participant_roles(conn, instance_id, person_id)
    if not roles:
        raise ArtifactError("not_permitted", 403, "Not a participant", "You are not part of this job.")
    return (*row, roles)


async def _fetch_version(conn: AsyncConnection, artifact_id: str, version: int) -> VersionRecord | None:
    cur = await conn.execute(
        "select artifact_id, version, content, content_hash, produced_by_kind, produced_by,"
        " inputs, sources, verification, created_at"
        " from work.artifact_versions where artifact_id = %s and version = %s",
        (artifact_id, version),
    )
    row = await cur.fetchone()
    if row is None:
        return None
    content = row[2] if isinstance(row[2], dict) else json.loads(row[2])
    inputs = row[6] if isinstance(row[6], list) else json.loads(row[6] or "[]")
    sources = row[7] if isinstance(row[7], list) else json.loads(row[7] or "[]")
    verification = row[8]
    if verification is not None and not isinstance(verification, dict):
        verification = json.loads(verification)
    cur2 = await conn.execute("select artifact_type, status from work.artifacts where id = %s", (artifact_id,))
    meta = await cur2.fetchone()
    artifact_type = meta[0] if meta else ""
    status = meta[1] if meta else "draft"
    return VersionRecord(
        artifact_id=artifact_id,
        artifact_type=artifact_type,
        version=int(row[1]),
        status=status,
        content=content,
        content_hash=row[3],
        produced_by_kind=row[4],
        produced_by=row[5],
        inputs=inputs,
        sources=sources,
        verification=verification,
        created_at=row[9],
    )


async def _version_history(conn: AsyncConnection, org: OrgModel, artifact_id: str) -> list[dict[str, Any]]:
    cur = await conn.execute(
        "select version, produced_by_kind, produced_by, created_at"
        " from work.artifact_versions where artifact_id = %s order by version",
        (artifact_id,),
    )
    rows = await cur.fetchall()
    seat_names = await _attempt_seat_names(conn, [str(r[2]) for r in rows if r[1] == "attempt"])
    items: list[dict[str, Any]] = []
    for version, kind, producer, created_at in rows:
        at = created_at.isoformat() if hasattr(created_at, "isoformat") else str(created_at)
        items.append(
            {
                "version": int(version),
                "by": _produced_by_name(org, kind, producer, seat_names),
                "at": at,
            }
        )
    return items


def _summary_from_row(
    org: OrgModel,
    *,
    artifact_id: str,
    artifact_type: str,
    name: str,
    status: str,
    latest_version: int,
    type_spec: ArtifactTypeSpec,
    viewer_roles: list[str],
    versions: list[dict[str, Any]] | None = None,
    classification_ceiling: Classification | None = None,
) -> dict[str, Any]:
    allowed = _apply_ceiling(_fields_for_roles(type_spec, viewer_roles), type_spec, classification_ceiling)
    summary: dict[str, Any] = {
        "artifact_id": artifact_id,
        "artifact_type": artifact_type,
        "name": name,
        "latest_version": latest_version,
        "status": status,
        "view": build_artifact_view(type_spec, allowed),
    }
    if versions is not None:
        summary["versions"] = versions
    return summary


async def get_artifact(
    conn: AsyncConnection,
    org: OrgModel,
    org_id: str,
    artifact_id: str,
    person_id: str,
    defs: dict[str, dict[str, dict]] | None = None,
) -> dict[str, Any]:
    row = await _artifact_context(conn, org_id, artifact_id, person_id)
    aid, _instance_id, artifact_type, name, status, latest_version, _pvid, viewer_roles = row
    if defs is None:
        from .instances import _load_definitions

        defs = await _load_definitions(conn, str(_pvid))
    at = parse_artifact_type(defs, artifact_type)
    versions = await _version_history(conn, org, aid)
    return _summary_from_row(
        org,
        artifact_id=aid,
        artifact_type=artifact_type,
        name=name,
        status=status,
        latest_version=int(latest_version),
        type_spec=at.spec,
        viewer_roles=viewer_roles,
        versions=versions,
    )


async def get_artifact_version(
    conn: AsyncConnection,
    org: OrgModel,
    org_id: str,
    artifact_id: str,
    version: int,
    person_id: str,
    defs: dict[str, dict[str, dict]] | None = None,
) -> dict[str, Any]:
    row = await _artifact_context(conn, org_id, artifact_id, person_id)
    aid, _instance_id, artifact_type, _name, _status, _lv, pvid, viewer_roles = row
    if defs is None:
        from .instances import _load_definitions

        defs = await _load_definitions(conn, str(pvid))
    at = parse_artifact_type(defs, artifact_type)
    rec = await _fetch_version(conn, aid, version)
    if rec is None:
        raise ArtifactError("not_found", 404, "Version not found", f"No version {version} for artifact {aid!r}.")
    projected = project(rec, at.spec, viewer_roles, latest_version=int(_lv))
    seat_names = (
        await _attempt_seat_names(conn, [rec.produced_by]) if rec.produced_by_kind == "attempt" else {}
    )
    projected["produced_by"]["name"] = _produced_by_name(org, rec.produced_by_kind, rec.produced_by, seat_names)
    return projected


async def summaries_for_instance(
    conn: AsyncConnection,
    org: OrgModel,
    instance_id: str,
    viewer_roles: list[str],
    defs: dict[str, dict[str, dict]],
) -> list[dict[str, Any]]:
    cur = await conn.execute(
        "select id, artifact_type, name, status, latest_version from work.artifacts"
        " where instance_id = %s order by artifact_type, key",
        (instance_id,),
    )
    out: list[dict[str, Any]] = []
    for aid, artifact_type, name, status, latest_version in await cur.fetchall():
        at = parse_artifact_type(defs, artifact_type)
        out.append(
            _summary_from_row(
                org,
                artifact_id=aid,
                artifact_type=artifact_type,
                name=name,
                status=status,
                latest_version=int(latest_version),
                type_spec=at.spec,
                viewer_roles=viewer_roles,
            )
        )
    return out


def artifact_type_audience_roles(type_spec: ArtifactTypeSpec) -> list[str]:
    roles: list[str] = []
    for role, vis in type_spec.visibility.items():
        if vis != "none":
            roles.append(role)
    return sorted(set(roles))


def _validate_field_value(name: str, field: FieldSpec, val: Any, pointer_prefix: str) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    if val is None:
        return errors
    ptr = f"{pointer_prefix}/{name}"
    if field.type == "integer" and not isinstance(val, int):
        errors.append({"pointer": ptr, "message": "must be an integer"})
    elif field.type in ("number", "money") and not isinstance(val, (int, float)):
        errors.append({"pointer": ptr, "message": f"must be a {field.type}"})
    elif field.type in ("string", "text", "date", "datetime") and not isinstance(val, str):
        errors.append({"pointer": ptr, "message": "must be a string"})
    elif field.type == "list" and not isinstance(val, list):
        errors.append({"pointer": ptr, "message": "must be a list"})
    elif field.type == "boolean" and not isinstance(val, bool):
        errors.append({"pointer": ptr, "message": "must be a boolean"})
    elif field.type == "object" and not isinstance(val, dict):
        errors.append({"pointer": ptr, "message": "must be an object"})
    return errors


def validate_artifact_content(
    type_spec: ArtifactTypeSpec,
    content: dict[str, Any],
    *,
    partial: bool = False,
) -> list[dict[str, str]]:
    """When partial=True (saveDraft), validate types of present fields only. When False, require required fields too."""
    errors: list[dict[str, str]] = []
    if type_spec.row_based:
        rows = content.get("rows")
        if not isinstance(rows, list):
            errors.append({"pointer": "/rows", "message": "rows must be an array"})
            return errors
        for i, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            if not partial:
                for name, field in type_spec.fields.items():
                    if field.required and name not in row:
                        errors.append({"pointer": f"/rows/{i}/{name}", "message": "required field missing"})
            for name, val in row.items():
                field = type_spec.fields.get(name)
                if field is None:
                    errors.append({"pointer": f"/rows/{i}/{name}", "message": "unknown field"})
                    continue
                errors.extend(_validate_field_value(name, field, val, f"/rows/{i}"))
        return errors
    if not isinstance(content, dict):
        errors.append({"pointer": "", "message": "content must be an object"})
        return errors
    if not partial:
        for name, field in type_spec.fields.items():
            if field.required and name not in content:
                errors.append({"pointer": f"/content/{name}", "message": "required field missing"})
    for name, val in content.items():
        field = type_spec.fields.get(name)
        if field is None:
            errors.append({"pointer": f"/content/{name}", "message": "unknown field"})
            continue
        errors.extend(_validate_field_value(name, field, val, "/content"))
    return errors


def _contract_allows_artifact_type(contract: dict[str, Any], artifact_type: str) -> bool:
    for item in contract.get("expected_outputs") or []:
        if item.get("artifact_type") == artifact_type:
            return True
    return False


async def save_draft_from_attempt(
    conn: AsyncConnection,
    *,
    org: OrgModel,
    gate: Any,
    body: dict[str, Any],
    defs: dict[str, dict[str, dict]],
    packs_dir: Path,
) -> dict[str, Any]:
    from datetime import timezone

    from .worker_fence import ClaimedAttempt

    if not isinstance(gate, ClaimedAttempt):
        raise RuntimeError("save_draft requires a claimed attempt")
    artifact_type = body["artifact_type"]
    if not _contract_allows_artifact_type(gate.contract, artifact_type):
        raise ArtifactError(
            "not_permitted",
            403,
            "Artifact type not allowed",
            f"{artifact_type!r} is not in this contract's expected outputs.",
        )
    at = parse_artifact_type(defs, artifact_type)
    content = body["content"]
    if not isinstance(content, dict):
        raise ArtifactError("validation_failed", 422, "Invalid content", "content must be an object.")
    field_errors = validate_artifact_content(at.spec, content, partial=True)
    if field_errors:
        raise ArtifactError(
            "validation_failed",
            422,
            "Draft content is invalid",
            "Fix the fields and try again.",
            errors=field_errors,
        )
    content_hash = hashlib.sha256(_canonical_json(content)).hexdigest()
    artifact_id = body.get("artifact_id")
    key = str(body.get("key") or "")
    base_version = body.get("base_version")
    inputs = body.get("inputs") or []
    sources = body.get("sources") or []
    item_key = at.spec.item_key
    if item_key:
        item = content.get(item_key)
        if not key or (item is not None and str(item) != key):
            raise ArtifactError(
                "validation_failed",
                422,
                "Draft key is invalid",
                f"Each {artifact_type} draft needs key equal to its {item_key}.",
                errors=[{"pointer": "/key", "message": f"must equal content.{item_key}"}],
            )
    elif key:
        raise ArtifactError(
            "validation_failed",
            422,
            "Draft key is invalid",
            f"{artifact_type} keeps one draft per job; send no key.",
            errors=[{"pointer": "/key", "message": "must be empty"}],
        )

    if artifact_id:
        cur = await conn.execute(
            "select a.id, a.instance_id, a.latest_version, a.artifact_type, a.name, a.key"
            " from work.artifacts a where a.id = %s for update",
            (artifact_id,),
        )
        row = await cur.fetchone()
        if row is None:
            raise ArtifactError("not_found", 404, "Artifact not found", f"No artifact {artifact_id!r}.")
        if row[1] != gate.instance_id:
            raise ArtifactError("not_permitted", 403, "Wrong job", "Artifact belongs to another job.")
        if row[3] != artifact_type:
            raise ArtifactError("validation_failed", 422, "Type mismatch", "artifact_id does not match artifact_type.")
        if str(row[5] or "") != key:
            raise ArtifactError("validation_failed", 422, "Key mismatch", "artifact_id does not match key.")
        latest = int(row[2])
        if base_version is not None and int(base_version) != latest:
            raise ArtifactError(
                "version_taken",
                409,
                "Version moved on",
                "Reload the artifact and save again.",
                current_version=latest,
            )
        name = row[4]
        new_version = latest + 1
    else:
        cur = await conn.execute(
            "select id, latest_version, name from work.artifacts"
            " where instance_id = %s and artifact_type = %s and key = %s"
            " for update",
            (gate.instance_id, artifact_type, key),
        )
        existing = await cur.fetchone()
        if existing is not None:
            artifact_id = existing[0]
            latest = int(existing[1])
            name = existing[2]
            if base_version is not None and int(base_version) != latest:
                raise ArtifactError(
                    "version_taken",
                    409,
                    "Version moved on",
                    "Reload the artifact and save again.",
                    current_version=latest,
                )
            new_version = latest + 1
        else:
            artifact_id = ids.new_artifact_id()
            type_name = artifact_type.replace("_", " ").title()
            name = str(content.get("title") or (f"{type_name} {key}" if key else type_name))
            await conn.execute(
                "insert into work.artifacts (id, instance_id, artifact_type, key, name, status, latest_version)"
                " values (%s, %s, %s, %s, %s, 'draft', 0)",
                (artifact_id, gate.instance_id, artifact_type, key, name),
            )
            new_version = 1
            if base_version is not None and int(base_version) != 0:
                raise ArtifactError(
                    "version_taken",
                    409,
                    "Version moved on",
                    "Reload the artifact and save again.",
                    current_version=0,
                )

    enriched_inputs: list[dict[str, Any]] = []
    for item in inputs:
        if not isinstance(item, dict):
            continue
        aid = item.get("artifact_id")
        ver = item.get("version")
        if not aid or ver is None:
            continue
        vcur = await conn.execute(
            "select content_hash from work.artifact_versions where artifact_id = %s and version = %s",
            (aid, int(ver)),
        )
        vrow = await vcur.fetchone()
        if vrow is None:
            raise ArtifactError("validation_failed", 422, "Unknown input version", f"No version {ver} for {aid!r}.")
        enriched_inputs.append(
            {"artifact_id": aid, "version": int(ver), "content_hash": vrow[0]}
        )

    await conn.execute(
        "insert into work.artifact_versions ("
        " artifact_id, version, content, content_hash, produced_by_kind, produced_by, inputs, sources"
        ") values (%s, %s, %s, %s, 'attempt', %s, %s, %s)",
        (
            artifact_id,
            new_version,
            Jsonb(content),
            content_hash,
            gate.attempt_id,
            Jsonb(enriched_inputs),
            Jsonb(sources if isinstance(sources, list) else []),
        ),
    )
    await conn.execute(
        "update work.artifacts set latest_version = %s, status = 'draft' where id = %s",
        (new_version, artifact_id),
    )

    from . import decisions as decision_ops
    from .outbox import ExecutionEventWrite, OutboxRow, append_outbox_many, write_execution_event

    await decision_ops.void_open_decisions_for_artifact(
        conn,
        instance_id=gate.instance_id,
        artifact_id=artifact_id,
        voided_by=gate.seat,
    )

    ref = f"{artifact_id}@{new_version}"
    produced_id = await write_execution_event(
        conn,
        ExecutionEventWrite(
            org_id=gate.org_id,
            run_id=gate.instance_id,
            event_type="ArtifactProduced",
            actor_kind="seat",
            actor_id=gate.seat,
            correlation_id=gate.correlation_id,
            redacted_summary=f"Saved draft {artifact_type} v{new_version}.",
            task_id=gate.task_id,
            attempt_id=gate.attempt_id,
            artifact_refs=[ref],
        ),
    )
    from . import events as workflow_events

    await workflow_events.evaluate_artifact_triggers(
        conn,
        org,
        gate.instance_id,
        artifact_type=artifact_type,
        content=content,
        packs_dir=packs_dir,
        cause=produced_id,
    )
    await decision_ops.open_ready_decisions(conn, gate.instance_id, org=org, packs_dir=packs_dir)
    audience_roles = artifact_type_audience_roles(at.spec)
    await append_outbox_many(
        conn,
        [
            OutboxRow(
                stream=ids.stream_instance(gate.instance_id),
                event_type="artifact.version_created",
                instance_id=gate.instance_id,
                audience={"roles": audience_roles},
                data={
                    "instance_id": gate.instance_id,
                    "artifact_id": artifact_id,
                    "artifact_type": artifact_type,
                    "version": new_version,
                    "status": "draft",
                    "by": gate.seat,
                },
            )
        ],
    )
    return {
        "artifact_id": artifact_id,
        "artifact_type": artifact_type,
        "version": new_version,
        "status": "draft",
        "content": content,
        "hidden_fields": [],
        "content_hash": content_hash,
        "produced_by": {"kind": "attempt", "id": gate.attempt_id},
        "inputs": enriched_inputs,
        "sources": sources if isinstance(sources, list) else [],
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }


async def create_artifact_version(
    conn: AsyncConnection,
    org: OrgModel,
    org_id: str,
    artifact_id: str,
    person_id: str,
    body: dict[str, Any],
    *,
    packs_dir: Path,
) -> dict[str, Any]:
    """Person-authored artifact version (M2 createArtifactVersion)."""
    from . import decisions as decision_ops
    from .instances import _load_definitions
    from .outbox import ExecutionEventWrite, OutboxRow, append_outbox_many, write_execution_event

    base_version = body.get("base_version")
    content = body.get("content")
    if base_version is None or not isinstance(content, dict):
        raise ArtifactError("validation_failed", 422, "Invalid body", "base_version and content are required.")

    cur = await conn.execute(
        "select a.id, a.instance_id, a.artifact_type, a.name, a.status, a.latest_version"
        " from work.artifacts a"
        " join work.instances i on i.id = a.instance_id and i.org_id = %s"
        " where a.id = %s",
        (org_id, artifact_id),
    )
    meta = await cur.fetchone()
    if meta is None:
        raise ArtifactError("not_found", 404, "Artifact not found", f"No artifact {artifact_id!r}.")
    _aid, instance_id, artifact_type, name, status, latest_version = meta

    inst_cur = await conn.execute(
        "select pack_version_id, correlation_id, seat from work.instances where id = %s for update",
        (instance_id,),
    )
    inst_row = await inst_cur.fetchone()
    if inst_row is None:
        raise ArtifactError("not_found", 404, "Job not found", "Artifact belongs to a missing job.")
    pack_version_id, correlation_id, seat_name = str(inst_row[0]), inst_row[1], inst_row[2]

    await conn.execute("select id from work.artifacts where id = %s for update", (artifact_id,))

    roles = await _participant_roles(conn, instance_id, person_id)
    if not roles:
        raise ArtifactError("not_permitted", 403, "Not a participant", "You are not part of this job.")

    latest = int(latest_version)
    if int(base_version) != latest:
        raise ArtifactError(
            "stale_version",
            409,
            "Version changed",
            "Reload the artifact and edit again.",
            current_version=latest,
        )

    defs = await _load_definitions(conn, pack_version_id)
    at = parse_artifact_type(defs, artifact_type)
    projected = await get_artifact_version(
        conn, org, org_id, artifact_id, latest, person_id, defs=defs
    )
    hidden = projected.get("hidden_fields") or []
    if hidden:
        raise ArtifactError(
            "not_permitted",
            403,
            "Cannot edit hidden fields",
            "You cannot save a version that would overwrite fields you cannot see.",
        )

    field_errors = validate_artifact_content(at.spec, content, partial=False)
    if field_errors:
        raise ArtifactError(
            "validation_failed",
            422,
            "Content is invalid",
            "Fix the fields and try again.",
            errors=field_errors,
        )

    pend_cur = await conn.execute(
        "select 1 from work.pending_items where instance_id = %s and status = 'open'"
        " and kind = 'decision' and artifact_ref->>'artifact_id' = %s limit 1",
        (instance_id, artifact_id),
    )
    has_open_decision = await pend_cur.fetchone() is not None
    if status in ("locked", "final"):
        if not has_open_decision:
            raise ArtifactError(
                "conflict",
                409,
                "Artifact cannot be edited",
                "This artifact is locked or final.",
            )

    content_hash = hashlib.sha256(_canonical_json(content)).hexdigest()
    new_version = latest + 1
    ts = clock.now()
    await conn.execute(
        "insert into work.artifact_versions ("
        " artifact_id, version, content, content_hash, produced_by_kind, produced_by, inputs, sources"
        ") values (%s, %s, %s, %s, 'person', %s, '[]'::jsonb, '[]'::jsonb)",
        (artifact_id, new_version, Jsonb(content), content_hash, person_id),
    )
    await conn.execute(
        "update work.artifacts set latest_version = %s, status = 'draft' where id = %s",
        (new_version, artifact_id),
    )

    await decision_ops.void_open_decisions_for_artifact(
        conn,
        instance_id=instance_id,
        artifact_id=artifact_id,
        voided_by=person_id,
    )

    produced_id = await write_execution_event(
        conn,
        ExecutionEventWrite(
            org_id=org_id,
            run_id=instance_id,
            event_type="ArtifactProduced",
            actor_kind="person",
            actor_id=person_id,
            correlation_id=correlation_id,
            redacted_summary=f"Edited {artifact_type} v{new_version}.",
            artifact_refs=[f"{artifact_id}@{new_version}"],
        ),
    )
    from . import events as workflow_events

    await workflow_events.evaluate_artifact_triggers(
        conn,
        org,
        instance_id,
        artifact_type=artifact_type,
        content=content,
        packs_dir=packs_dir,
        cause=produced_id,
    )
    audience_roles = artifact_type_audience_roles(at.spec)
    await append_outbox_many(
        conn,
        [
            OutboxRow(
                stream=ids.stream_instance(instance_id),
                event_type="artifact.version_created",
                instance_id=instance_id,
                audience={"roles": audience_roles},
                data={
                    "instance_id": instance_id,
                    "artifact_id": artifact_id,
                    "artifact_type": artifact_type,
                    "version": new_version,
                    "status": "draft",
                    "by": person_id,
                },
            )
        ],
    )

    await decision_ops.open_ready_decisions(conn, instance_id, org=org, packs_dir=packs_dir)

    out = project(
        VersionRecord(
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            version=new_version,
            status="draft",
            content=content,
            content_hash=content_hash,
            produced_by_kind="person",
            produced_by=person_id,
            inputs=[],
            sources=[],
            verification=None,
            created_at=ts,
        ),
        at.spec,
        roles,
        latest_version=new_version,
    )
    out["produced_by"]["name"] = _produced_by_name(org, "person", person_id)
    return out
