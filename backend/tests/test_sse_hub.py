"""Unit tests for the outbox SSE hub (M1-BE-04 B)."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from aos.sse import OutboxHub, Subscriber, format_sse_outbox


class SseHubTests(unittest.IsolatedAsyncioTestCase):
    async def test_dedupes_seq_already_delivered(self) -> None:
        hub = OutboxHub("postgresql://unused", heartbeat_seconds=60.0)
        sub = Subscriber(
            stream="instance:JX-0001",
            person_id="faisal",
            org_id="org_demo",
            instance_id="JX-0001",
            last_delivered_seq=2,
        )
        rows = [
            (
                "instance:JX-0001",
                2,
                "turn.created",
                "JX-0001",
                {"roles": ["requester"]},
                {"instance_id": "JX-0001", "turn": {}},
                None,
            ),
            (
                "instance:JX-0001",
                3,
                "turn.created",
                "JX-0001",
                {"roles": ["requester"]},
                {"instance_id": "JX-0001", "turn": {}},
                None,
            ),
        ]
        hub._pool = MagicMock()

        with (
            patch("aos.sse.streaming.participant_roles", AsyncMock(return_value=["requester"])),
            patch("aos.sse.streaming.outbox_visible", return_value=True),
            patch("aos.sse.streaming.outbox_row_to_ui_event") as proj,
        ):
            proj.side_effect = lambda **kw: {
                "id": f"instance:JX-0001:{kw['seq']}",
                "type": kw["event_type"],
                "at": "t",
                "data": kw["data"],
            }
            await hub._deliver_rows_to_subscriber(sub, rows)

        self.assertEqual(sub.last_delivered_seq, 3)
        chunks = []
        while not sub.queue.empty():
            chunks.append(sub.queue.get_nowait())
        self.assertEqual(len(chunks), 1)
        self.assertIn("instance:JX-0001:3", chunks[0])

    async def test_slow_client_dropped_on_full_queue(self) -> None:
        sub = Subscriber(
            stream="instance:JX-0001",
            person_id="faisal",
            org_id="org_demo",
            instance_id="JX-0001",
            last_delivered_seq=0,
        )
        event = {"id": "instance:JX-0001:1", "type": "turn.created", "at": "t", "data": {}}
        chunk = format_sse_outbox(event)
        for _ in range(sub.queue.maxsize):
            self.assertTrue(sub.try_push(chunk))
        self.assertFalse(sub.try_push(chunk))
        self.assertTrue(sub.closed)


if __name__ == "__main__":
    unittest.main()
