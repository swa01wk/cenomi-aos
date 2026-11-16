"""Shared RFQ attachments on a job."""

from __future__ import annotations

import asyncio
import unittest

import psycopg

from aos.kernel import shared_attachments
from aos.kernel.org import load_org
from aos.kernel.settings import REPO

from . import _pg

ORG = load_org(REPO / "seed" / "org.yaml")
ORG_ID = ORG.organization.id


@unittest.skipUnless(_pg.available(), "needs Postgres")
class SharedAttachmentsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.db = _pg.create_migrated()

    @classmethod
    def tearDownClass(cls) -> None:
        _pg.drop(cls.db)

    def test_upload_list_and_delete(self) -> None:
        inst = "QQ-SHA1"

        async def run() -> None:
            async with await psycopg.AsyncConnection.connect(_pg.kernel_url(self.db)) as conn:
                async with conn.transaction():
                    await conn.execute(
                        "insert into work.instances (id, org_id, title, workflow, pack_version_id, state, version,"
                        " seat, seat_version, status, attributes)"
                        " values (%s, %s, 't', 'quick_quote',"
                        " (select id from registry.pack_versions limit 1),"
                        " 'rfq_sending', 1, 'seat_sourcing_poc', 1, 'running', '{}')",
                        (inst, ORG_ID),
                    )
                    await conn.execute(
                        "insert into work.participants (instance_id, role, person_id, bound_by)"
                        " values (%s, 'buyer', 'noura', 'claim')",
                        (inst,),
                    )
                    att = await shared_attachments.upload(
                        conn,
                        org_id=ORG_ID,
                        instance_id=inst,
                        person_id="noura",
                        filename="spec.pdf",
                        content_type="application/pdf",
                        data=b"%PDF-1.4 demo",
                    )
                    self.assertEqual(att["filename"], "spec.pdf")
                    listed = await shared_attachments.list_for_snapshot(conn, org_id=ORG_ID, instance_id=inst)
                    self.assertEqual(len(listed), 1)
                    names = await shared_attachments.filenames_for_instance(conn, inst)
                    self.assertEqual(names, ["spec.pdf"])
                    await shared_attachments.delete_attachment(
                        conn,
                        org_id=ORG_ID,
                        instance_id=inst,
                        person_id="noura",
                        attachment_id=att["attachment_id"],
                    )
                    self.assertEqual(await shared_attachments.filenames_for_instance(conn, inst), [])

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
