"""Quote count sync for timer transitions (POC)."""

from __future__ import annotations

import json
import unittest

import psycopg

from aos.kernel import ids, quotes
from aos.kernel.contracts import _canonical_json

from . import _pg


@unittest.skipUnless(_pg.available(), "no local Postgres")
class QuoteCountSyncTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.db = _pg.create_migrated()
        self.conn = await psycopg.AsyncConnection.connect(_pg.kernel_url(self.db))

    async def asyncTearDown(self) -> None:
        await self.conn.close()
        _pg.drop(self.db)

    async def test_counts_quote_without_artifact_key(self) -> None:
        inst = "QQ-QS1"
        await self.conn.execute(
            """
            insert into work.instances (
              id, org_id, workflow, pack_version_id, seat, seat_version, title, state, version,
              attributes, created_by, correlation_id
            ) values (%s, 'org_poc', 'quick_quote', 'pv1', 'seat', 1, 'T', 'awaiting_quotes', 1,
                      '{"invited_count": 3}'::jsonb, 'faisal', 'c1')
            """,
            (inst,),
        )
        aid = ids.new_artifact_id()
        content = {
            "supplier": "Webknot",
            "unit_price": 100,
            "total": 500,
            "lead_time_days": 5,
            "received_at": "2026-11-02T12:00:00Z",
        }
        ch = __import__("hashlib").sha256(_canonical_json(content)).hexdigest()
        await self.conn.execute(
            "insert into work.artifacts (id, instance_id, artifact_type, key, name, status, latest_version)"
            " values (%s, %s, 'quote', '', 'Quote', 'draft', 1)",
            (aid, inst),
        )
        await self.conn.execute(
            "insert into work.artifact_versions (artifact_id, version, content, content_hash,"
            " produced_by_kind, produced_by, inputs, sources)"
            " values (%s, 1, %s, %s, 'attempt', 'att', '[]', '[]')",
            (aid, json.dumps(content), ch),
        )
        count = await quotes.sync_quote_count_attribute(self.conn, inst)
        self.assertEqual(count, 1)
        cur = await self.conn.execute("select attributes->>'quote_count' from work.instances where id = %s", (inst,))
        self.assertEqual((await cur.fetchone())[0], "1")


if __name__ == "__main__":
    unittest.main()
