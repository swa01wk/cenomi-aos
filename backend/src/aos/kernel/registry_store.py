"""Pack sync: load a pack folder, validate it against the organization, store it as a pack version.

A sync is idempotent on (pack, version, digest). Changing a pack without bumping
``metadata.version`` is allowed while that version is unpublished (a new draft row with the new
digest); once a version is published, its number is taken and the sync is refused (ADR 009).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from ..registry import load_pack, validate_pack
from . import audit_store
from .org import OrgModel


class PackNotFound(Exception):
    pass


class VersionTaken(Exception):
    pass


@dataclass(frozen=True)
class SyncResult:
    pack_version_id: str
    pack: str
    version: int
    digest: str
    status: str
    created: bool
    report: dict


def pack_root(packs_dir: Path, name: str) -> Path:
    root = (packs_dir / name).resolve()
    if root.parent != packs_dir.resolve() or not (root / "pack.yaml").is_file():
        raise PackNotFound(name)
    return root


def available_packs(packs_dir: Path) -> list[str]:
    return sorted(p.parent.name for p in packs_dir.glob("*/pack.yaml"))


def _digest(spec: dict) -> str:
    return hashlib.sha256(json.dumps(spec, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


async def sync_pack(conn: AsyncConnection, *, org: OrgModel, packs_dir: Path, name: str, actor: str,
                    source: str = "local") -> SyncResult:
    root = pack_root(packs_dir, name)
    pack = load_pack(root)
    report = validate_pack(root, org=org.as_validation_org())
    if pack.manifest is None:
        raise PackNotFound(f"{name}: no Pack manifest")
    meta = pack.manifest.metadata
    org_id = org.organization.id

    await conn.execute("insert into registry.packs (org_id, name, owner) values (%s, %s, %s) on conflict do nothing",
                       (org_id, meta.name, meta.owner))
    cur = await conn.execute(
        "select id, digest, status from registry.pack_versions where org_id = %s and pack_name = %s and version = %s",
        (org_id, meta.name, meta.version))
    rows = await cur.fetchall()
    for vid, digest, status in rows:
        if digest == pack.digest:
            return SyncResult(str(vid), meta.name, meta.version, digest, status, False, report.to_dict())
        if status == "published":
            raise VersionTaken(f"{meta.name} v{meta.version} is published with a different digest; "
                               "bump metadata.version in pack.yaml")

    status = "validated" if report.ok else "invalid"
    cur = await conn.execute(
        "insert into registry.pack_versions (org_id, pack_name, version, digest, source, status, validation, created_by)"
        " values (%s, %s, %s, %s, %s, %s, %s, %s) returning id",
        (org_id, meta.name, meta.version, pack.digest, source, status, Jsonb(report.to_dict()), actor))
    vid = (await cur.fetchone())[0]

    defs = [("Pack", meta.name, pack.manifest, "pack.yaml")]
    defs += [(kind, n, obj, pack.files[(kind, n)]) for kind, objs in pack.objects.items() for n, obj in objs.items()]
    async with conn.cursor() as c:
        await c.executemany(
            "insert into registry.definitions (pack_version_id, kind, name, version, spec, digest, file)"
            " values (%s, %s, %s, %s, %s, %s, %s)",
            [(vid, kind, n, obj.metadata.version, Jsonb(spec := obj.model_dump(mode="json", by_alias=True)),
              _digest(spec), file) for kind, n, obj, file in defs])

    await audit_store.record(conn, org_id=org_id, actor=actor, action=f"pack.{status}",
                             subject=f"{meta.name}@v{meta.version}",
                             data={"pack_version_id": str(vid), "digest": pack.digest, "source": source,
                                   "errors": len(report.errors), "warnings": len(report.warnings),
                                   "definitions": len(defs)})
    return SyncResult(str(vid), meta.name, meta.version, pack.digest, status, True, report.to_dict())


async def list_packs(conn: AsyncConnection, org_id: str) -> list[dict]:
    cur = await conn.execute(
        "select p.name, p.owner, v.id, v.version, v.digest, v.status, v.source, v.created_by, v.created_at,"
        " (v.validation->>'ok')::boolean, jsonb_array_length(coalesce(v.validation->'errors', '[]')),"
        " jsonb_array_length(coalesce(v.validation->'warnings', '[]'))"
        " from registry.packs p left join registry.pack_versions v on v.org_id = p.org_id and v.pack_name = p.name"
        " where p.org_id = %s order by p.name, v.created_at desc", (org_id,))
    packs: dict[str, dict] = {}
    for name, owner, vid, version, digest, status, source, by, at, ok, errors, warnings in await cur.fetchall():
        p = packs.setdefault(name, {"name": name, "owner": owner, "versions": []})
        if vid is not None:
            p["versions"].append({"id": str(vid), "version": version, "digest": digest, "status": status,
                                  "source": source, "created_by": by, "created_at": at.isoformat(),
                                  "ok": ok, "errors": errors, "warnings": warnings})
    return list(packs.values())


async def get_version(conn: AsyncConnection, org_id: str, version_id: str) -> dict | None:
    cur = await conn.execute(
        "select id, pack_name, version, digest, status, source, validation, created_by, created_at"
        " from registry.pack_versions where org_id = %s and id = %s", (org_id, version_id))
    row = await cur.fetchone()
    if row is None:
        return None
    defs = await (await conn.execute(
        "select kind, name, version, file, digest from registry.definitions where pack_version_id = %s"
        " order by kind, name", (version_id,))).fetchall()
    return {"id": str(row[0]), "pack": row[1], "version": row[2], "digest": row[3], "status": row[4],
            "source": row[5], "validation": row[6], "created_by": row[7], "created_at": row[8].isoformat(),
            "definitions": [{"kind": k, "name": n, "version": v, "file": f, "digest": d} for k, n, v, f, d in defs]}


async def get_definition(conn: AsyncConnection, version_id: str, kind: str, name: str) -> dict | None:
    row = await (await conn.execute(
        "select spec from registry.definitions where pack_version_id = %s and kind = %s and name = %s",
        (version_id, kind, name))).fetchone()
    return row[0] if row else None
