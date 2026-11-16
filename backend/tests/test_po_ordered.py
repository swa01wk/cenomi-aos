"""PO placed announcement on job close."""

from __future__ import annotations

import json
import unittest

import psycopg
from psycopg.rows import dict_row

from aos.kernel.org import load_org, seed_sql
from aos.kernel.po_ordered import post_po_ordered_announcement_if_needed


class PoOrderedTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.org = load_org("seed/org.yaml")
        cls.url = "postgresql://aos_kernel:aos_kernel_dev@127.0.0.1:5432/aos"

    async def test_announces_once_when_po_payload_exists(self) -> None:
        inst = "QQ-PO-TEST-1"
        async with await psycopg.AsyncConnection.connect(self.url, row_factory=dict_row) as conn:
            await conn.execute(seed_sql(self.org))
            await conn.execute(
                "insert into work.instances (id, org_id, workflow, pack_version_id, seat, seat_version,"
                " state, version, status, title, attributes, correlation_id, created_by, idempotency_key)"
                " values (%s, 'org_demo', 'quick_quote', (select id from registry.pack_versions limit 1),"
                " 'seat_sourcing_poc', 1, 'closed', 1, 'closed', 'Test', '{}', gen_random_uuid(), 'noura', 'k1')"
                " on conflict do nothing",
                (inst,),
            )
            await conn.execute(
                "insert into work.artifacts (id, instance_id, artifact_type, key, name, status, latest_version)"
                " values ('art_po_t', %s, 'po_payload', '', 'PO', 'draft', 1) on conflict do nothing",
                (inst,),
            )
            content = {
                "supplier_id": "SUP-11632",
                "reference": "AOS-PO-TEST",
                "ship_to": "Riyadh",
                "need_by": "2026-12-01",
                "currency": "SAR",
                "lines": [{"item": "Phone", "quantity": 1, "unit_price": 4900}],
                "po_amount": 4900,
            }
            await conn.execute(
                "insert into work.artifact_versions (artifact_id, version, content, content_hash,"
                " produced_by_kind, produced_by, inputs, sources)"
                " values ('art_po_t', 1, %s, 'abc', 'person', 'noura', '[]', '[]')"
                " on conflict do nothing",
                (json.dumps(content),),
            )
            first = await post_po_ordered_announcement_if_needed(
                conn, org=self.org, org_id="org_demo", instance_id=inst
            )
            second = await post_po_ordered_announcement_if_needed(
                conn, org=self.org, org_id="org_demo", instance_id=inst
            )
            self.assertTrue(first)
            self.assertFalse(second)
            cur = await conn.execute(
                "select blocks from work.turns where instance_id = %s and author_kind = 'seat'",
                (inst,),
            )
            rows = await cur.fetchall()
            self.assertEqual(len(rows), 1)
            self.assertIn("AOS-PO-TEST", json.dumps(rows[0]["blocks"]))


if __name__ == "__main__":
    unittest.main()
