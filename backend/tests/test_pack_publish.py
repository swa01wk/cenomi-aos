"""Pack publish helper: auto-bump when a published version blocks sync."""

from __future__ import annotations

import asyncio
import shutil
import tempfile
import unittest
from pathlib import Path

import psycopg
import yaml

from aos.kernel.org import load_org
from aos.kernel.pack_publish import bump_pack_manifest_version, ensure_pack_published
from aos.kernel.registry_store import sync_pack
from aos.kernel.settings import REPO

from . import _pg

ORG = load_org(REPO / "seed" / "org.yaml")


@unittest.skipUnless(_pg.available(), "no local Postgres")
class PackPublishTests(unittest.TestCase):
    def test_bump_pack_manifest_version(self) -> None:
        packs = Path(tempfile.mkdtemp(prefix="aos-pack-bump-"))
        try:
            shutil.copytree(REPO / "packs" / "procurement_demo", packs / "procurement_demo")
            path = packs / "procurement_demo" / "pack.yaml"
            before = yaml.safe_load(path.read_text())["metadata"]["version"]
            new = bump_pack_manifest_version(packs, "procurement_demo")
            self.assertEqual(new, int(before) + 1)
            after = yaml.safe_load(path.read_text())["metadata"]["version"]
            self.assertEqual(after, new)
        finally:
            shutil.rmtree(packs, ignore_errors=True)

    def test_ensure_pack_published_bumps_when_version_taken(self) -> None:
        db = _pg.create_migrated()
        packs = Path(tempfile.mkdtemp(prefix="aos-pack-ensure-"))
        try:
            shutil.copytree(REPO / "packs" / "procurement_demo", packs / "procurement_demo")
            path = packs / "procurement_demo" / "pack.yaml"
            base_version = yaml.safe_load(path.read_text())["metadata"]["version"]

            async def first_sync() -> str:
                async with await psycopg.AsyncConnection.connect(_pg.kernel_url(db)) as conn:
                    async with conn.transaction():
                        r = await sync_pack(
                            conn, org=ORG, packs_dir=packs, name="procurement_demo", actor="test"
                        )
                        await conn.execute(
                            "update registry.pack_versions set status = 'published' where id = %s",
                            (r.pack_version_id,),
                        )
                        return r.pack_version_id

            asyncio.run(first_sync())

            path.write_text(path.read_text() + "\n# drift\n")

            async def ensure() -> int:
                async with await psycopg.AsyncConnection.connect(_pg.kernel_url(db)) as conn:
                    async with conn.transaction():
                        r = await ensure_pack_published(
                            conn,
                            org=ORG,
                            packs_dir=packs,
                            name="procurement_demo",
                            actor="test-ensure",
                        )
                        return r.version

            new_version = asyncio.run(ensure())
            self.assertEqual(new_version, int(base_version) + 1)
            bumped = yaml.safe_load(path.read_text())["metadata"]["version"]
            self.assertEqual(bumped, new_version)
        finally:
            _pg.drop(db)
            shutil.rmtree(packs, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
