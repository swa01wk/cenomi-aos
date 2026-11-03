"""Publish on-disk packs and point active seats at the latest version (local dev / demo)."""

from __future__ import annotations

from pathlib import Path

import yaml
from psycopg import AsyncConnection

from . import registry_store
from .contracts import PackMaterialError, verify_pinned_pack_on_disk
from .org import OrgModel
from .registry_store import SyncResult, VersionTaken
from .seats import insert_seats_for_published_pack


def bump_pack_manifest_version(packs_dir: Path, pack_name: str) -> int:
    """Increment ``metadata.version`` in pack.yaml when a published version blocked sync."""
    path = packs_dir / pack_name / "pack.yaml"
    if not path.is_file():
        raise registry_store.PackNotFound(pack_name)
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    meta = doc.setdefault("metadata", {})
    current = int(meta.get("version") or 0)
    new_ver = current + 1
    meta["version"] = new_ver
    path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return new_ver


async def publish_pack_version(conn: AsyncConnection, *, org_id: str, pack_version_id: str) -> None:
    await conn.execute(
        "update registry.pack_versions set status = 'published',"
        " published_at = coalesce(published_at, now()) where id = %s",
        (pack_version_id,),
    )


async def _pack_meta(conn: AsyncConnection, org_id: str, pack_version_id: str) -> tuple[str, int, str]:
    cur = await conn.execute(
        "select pack_name, version, digest from registry.pack_versions where id = %s and org_id = %s",
        (pack_version_id, org_id),
    )
    row = await cur.fetchone()
    if row is None:
        raise registry_store.PackNotFound(f"pack_version_id={pack_version_id!r}")
    return str(row[0]), int(row[1]), str(row[2])


def _pack_pin_ok(packs_dir: Path, pack_name: str, pack_version: int, digest: str) -> bool:
    try:
        verify_pinned_pack_on_disk(packs_dir, pack_name, pack_version, digest)
    except PackMaterialError:
        return False
    return True


async def realign_running_instances_to_seat_pack(
    conn: AsyncConnection,
    *,
    org_id: str,
    packs_dir: Path,
) -> int:
    """After publish, move running jobs onto the seat's pack pin when their pin fails the disk check."""
    cur = await conn.execute(
        "select id, seat, seat_version, pack_version_id from work.instances"
        " where org_id = %s and status = 'running'",
        (org_id,),
    )
    updated = 0
    for instance_id, seat_name, seat_version, pvid in await cur.fetchall():
        if await heal_instance_pack_pin(
            conn,
            org_id=org_id,
            instance_id=str(instance_id),
            packs_dir=packs_dir,
        ):
            updated += 1
    return updated


async def heal_instance_pack_pin(
    conn: AsyncConnection,
    *,
    org_id: str,
    instance_id: str,
    packs_dir: Path,
) -> bool:
    """Point one job at the seat's published pack when its pin no longer matches disk."""
    cur = await conn.execute(
        "select seat, seat_version, pack_version_id from work.instances where id = %s and org_id = %s",
        (instance_id, org_id),
    )
    row = await cur.fetchone()
    if row is None:
        return False
    seat_name, seat_version, pvid = str(row[0]), int(row[1]), str(row[2])
    pack_name, pack_ver, pack_digest = await _pack_meta(conn, org_id, pvid)
    if _pack_pin_ok(packs_dir, pack_name, pack_ver, pack_digest):
        return False
    scur = await conn.execute(
        "select pack_version_id from registry.seats where org_id = %s and name = %s and version = %s",
        (org_id, seat_name, seat_version),
    )
    srow = await scur.fetchone()
    if srow is None:
        return False
    seat_pvid = str(srow[0])
    if seat_pvid == pvid:
        return False
    sname, sver, sdigest = await _pack_meta(conn, org_id, seat_pvid)
    if not _pack_pin_ok(packs_dir, sname, sver, sdigest):
        return False
    await conn.execute(
        "update work.instances set pack_version_id = %s where id = %s",
        (seat_pvid, instance_id),
    )
    return True


async def repoint_org_seats(conn: AsyncConnection, *, org_id: str, pack_version_id: str) -> list[str]:
    cur = await conn.execute(
        "update registry.seats set pack_version_id = %s where org_id = %s returning name",
        (pack_version_id, org_id),
    )
    return [str(row[0]) for row in await cur.fetchall()]


async def ensure_pack_published(
    conn: AsyncConnection,
    *,
    org: OrgModel,
    packs_dir: Path,
    name: str,
    actor: str,
    bump_on_version_taken: bool = True,
) -> SyncResult:
    """Sync the pack folder into Postgres, publish it, and repoint all seats. Idempotent when digest unchanged."""
    org_id = org.organization.id
    try:
        result = await registry_store.sync_pack(
            conn, org=org, packs_dir=packs_dir, name=name, actor=actor
        )
    except VersionTaken:
        if not bump_on_version_taken:
            raise
        bump_pack_manifest_version(packs_dir, name)
        result = await registry_store.sync_pack(
            conn, org=org, packs_dir=packs_dir, name=name, actor=f"{actor}:bump"
        )
    await publish_pack_version(conn, org_id=org_id, pack_version_id=result.pack_version_id)
    await insert_seats_for_published_pack(conn, org=org, org_id=org_id, pack_version_id=result.pack_version_id)
    await conn.execute(
        "update registry.seats set state = 'ACTIVE', configured_by = 'platform_admin',"
        " activated_by = 'head_of_procurement'"
        " where org_id = %s and name = 'seat_workspace_coordinator'"
        " and state in ('DRAFT', 'CONFIGURED', 'TESTING')",
        (org_id,),
    )
    await repoint_org_seats(conn, org_id=org_id, pack_version_id=result.pack_version_id)
    await realign_running_instances_to_seat_pack(conn, org_id=org_id, packs_dir=packs_dir)
    return result


async def ensure_all_packs_published(
    conn: AsyncConnection,
    *,
    org: OrgModel,
    packs_dir: Path,
    actor: str,
) -> list[SyncResult]:
    out: list[SyncResult] = []
    for name in registry_store.available_packs(packs_dir):
        out.append(
            await ensure_pack_published(
                conn, org=org, packs_dir=packs_dir, name=name, actor=actor
            )
        )
    return out
