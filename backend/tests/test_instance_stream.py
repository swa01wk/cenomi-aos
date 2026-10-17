"""M1-BE-04 (PR B): instance SSE stream (uvicorn + httpx)."""

from __future__ import annotations

import asyncio
import json
import shutil
import socket
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path
from typing import Any

import httpx
import psycopg
import uvicorn

from aos.api import create_app
from aos.kernel import ids
from aos.kernel.org import load_org
from aos.kernel.outbox import append_outbox
from aos.kernel.seats import insert_seats_for_published_pack
from aos.kernel.settings import REPO, Settings

from . import _pg

ORG = load_org(REPO / "seed" / "org.yaml")
SEAT = "seat_sourcing_poc"
WORKFLOW = "quick_quote"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _parse_sse_block(block: str) -> dict[str, Any]:
    out: dict[str, Any] = {"id": None, "event": None, "data": None, "comment": None}
    for line in block.split("\n"):
        if not line:
            continue
        if line.startswith(":"):
            out["comment"] = line[1:].strip()
        elif line.startswith("id:"):
            out["id"] = line[3:].strip()
        elif line.startswith("event:"):
            out["event"] = line[6:].strip()
        elif line.startswith("data:"):
            out["data"] = json.loads(line[5:].strip())
    return out


def _collect_sse(
    url: str,
    headers: dict[str, str],
    *,
    timeout: float,
    max_blocks: int | None = None,
) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    deadline = time.monotonic() + timeout
    read_timeout = max(timeout, 30.0)
    with httpx.Client(timeout=httpx.Timeout(read_timeout, connect=5.0)) as client:
        with client.stream("GET", url, headers=headers) as resp:
            resp.raise_for_status()
            buf = ""
            for chunk in resp.iter_text():
                if time.monotonic() > deadline:
                    break
                buf += chunk
                while "\n\n" in buf:
                    raw, buf = buf.split("\n\n", 1)
                    if not raw.strip():
                        continue
                    blocks.append(_parse_sse_block(raw))
                    if max_blocks is not None and len(blocks) >= max_blocks:
                        return blocks
    return blocks


class _UvicornServer:
    def __init__(self, app, port: int) -> None:
        self._server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
        )
        self._thread = threading.Thread(target=lambda: asyncio.run(self._server.serve()), daemon=True)

    def start(self, port: int, timeout: float = 20.0) -> None:
        self._thread.start()
        url = f"http://127.0.0.1:{port}/api/healthz"
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                if httpx.get(url, timeout=1.0).status_code == 200:
                    return
            except httpx.HTTPError:
                time.sleep(0.05)
        raise TimeoutError("API server did not become ready")

    def stop(self) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=10.0)


@unittest.skipUnless(_pg.available(), "no local Postgres")
class InstanceStreamTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.db = _pg.create_migrated()
        cls.packs = Path(tempfile.mkdtemp(prefix="aos-packs-stream-"))
        shutil.copytree(REPO / "packs" / "procurement_demo", cls.packs / "procurement_demo")
        cls.port = _free_port()
        cls.settings = Settings.from_env(
            database_url=_pg.kernel_url(cls.db),
            packs_dir=cls.packs,
            session_secret="test-secret-" + "x" * 40,
            sse_heartbeat_seconds=0.25,
        )
        cls.app = create_app(cls.settings)
        cls.server = _UvicornServer(cls.app, cls.port)
        cls.server.start(cls.port)
        cls.base = f"http://127.0.0.1:{cls.port}/api"
        cls.client = httpx.Client(base_url=cls.base, timeout=30.0)
        cls.version_id = cls.client.post(
            "/console/packs/procurement_demo/sync",
            headers=cls._auth("platform_admin"),
            json={"source": "test"},
        ).json()["pack_version_id"]
        cls._publish_once()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client.close()
        cls.server.stop()
        _pg.drop(cls.db)
        shutil.rmtree(cls.packs, ignore_errors=True)

    @classmethod
    def _auth(cls, person: str) -> dict[str, str]:
        token = cls.client.post("/auth/session", json={"person_id": person}).json()["token"]
        return {"Authorization": f"Bearer {token}"}

    def login(self, person: str) -> dict[str, str]:
        return self._auth(person)

    @classmethod
    def _publish_once(cls) -> None:
        cls.client.post(
            f"/console/pack-versions/{cls.version_id}/publish-requests",
            headers=cls._auth("platform_admin"),
        )
        req = cls.client.get("/console/publish-requests", headers=cls._auth("risk")).json()["items"][0]
        cls.client.post(
            f"/console/publish-requests/{req['id']}/approve",
            headers=cls._auth("risk"),
            json={"part": "policies"},
        )
        cls.client.post(
            f"/console/publish-requests/{req['id']}/approve",
            headers=cls._auth("head_of_procurement"),
            json={"part": "seats_and_workflows"},
        )

    def _ensure_seats(self) -> None:
        async def _run() -> None:
            async with await psycopg.AsyncConnection.connect(_pg.kernel_url(self.db)) as conn:
                async with conn.transaction():
                    await insert_seats_for_published_pack(
                        conn, org=ORG, org_id=ORG.organization.id, pack_version_id=self.version_id
                    )

        asyncio.run(_run())

    def _activate_seat(self) -> None:
        self._ensure_seats()
        seat = self.client.get(f"/console/seats/{SEAT}", headers=self.login("platform_admin")).json()
        configured = self.client.post(
            f"/console/seats/{SEAT}/configure",
            headers=self.login("platform_admin"),
            json={"version": 1, "expected_version": seat["record_version"]},
        ).json()
        rv = configured["record_version"]
        _pg.admin_sql(
            self.db,
            f"""
            update registry.seats
            set state = 'APPROVED', record_version = {rv}
            where org_id = (select id from org.organizations limit 1)
              and name = '{SEAT}' and version = 1;
            insert into registry.eval_runs (id, org_id, seat, seat_version, suite, model, status, passed, total)
            values
              ('ev_stream_refusals', (select id from org.organizations limit 1), '{SEAT}', 1,
               'refusals', 'fake', 'passed', 4, 4),
              ('ev_stream_dry_run', (select id from org.organizations limit 1), '{SEAT}', 1,
               'dry_run', 'fake', 'passed', 1, 1)
            on conflict (id) do nothing;
            """,
        )
        r = self.client.post(
            f"/console/seats/{SEAT}/activate",
            headers=self.login("head_of_procurement"),
            json={"version": 1, "expected_version": rv},
        )
        self.assertEqual(r.status_code, 200, r.text)

    def _start(self, person: str = "faisal") -> dict[str, Any]:
        r = self.client.post(
            "/instances",
            headers=self.login(person),
            json={"seat": SEAT, "workflow": WORKFLOW, "first_message": "Stream test message"},
        )
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()

    def setUp(self) -> None:
        _pg.admin_sql(
            self.db,
            """
            delete from evidence.outbox;
            delete from evidence.execution_events;
            delete from work.turns;
            delete from work.attempts;
            delete from work.tasks;
            delete from work.participants;
            delete from work.instances;
            delete from gov.budget_ledger;
            delete from gov.decision_records where event = 'admission.denied';
            update registry.seats set state = 'DRAFT', record_version = 1, configured_by = null, activated_by = null,
                pack_version_id = '%s'
            where name = 'seat_sourcing_poc';
            """
            % self.version_id,
        )

    def _events_url(self, inst_id: str, *, cursor: str | None = None) -> str:
        url = f"{self.base}/instances/{inst_id}/events"
        if cursor is not None:
            url = f"{url}?cursor={cursor}"
        return url

    def test_non_participant_gets_403(self) -> None:
        self._activate_seat()
        snap = self._start()
        inst_id = snap["instance_id"]
        r = self.client.get(self._events_url(inst_id), headers=self.login("khalid"))
        self.assertEqual(r.status_code, 403, r.text)
        self.assertEqual(r.json()["code"], "not_permitted")

    def test_no_cursor_snapshot_required(self) -> None:
        self._activate_seat()
        inst_id = self._start()["instance_id"]
        blocks = _collect_sse(
            self._events_url(inst_id),
            headers=self.login("faisal"),
            timeout=2.0,
            max_blocks=1,
        )
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["data"]["type"], "snapshot.required")
        self.assertEqual(blocks[0]["data"]["data"]["reason"], "cursor_unknown")

    def test_unknown_cursor_snapshot_required(self) -> None:
        self._activate_seat()
        inst_id = self._start()["instance_id"]
        stream = ids.stream_instance(inst_id)
        blocks = _collect_sse(
            self._events_url(inst_id),
            headers={**self.login("faisal"), "Last-Event-ID": f"{stream}:999999"},
            timeout=2.0,
            max_blocks=1,
        )
        self.assertEqual(blocks[0]["data"]["type"], "snapshot.required")
        self.assertEqual(blocks[0]["data"]["data"]["reason"], "cursor_unknown")

    def test_resume_without_duplicates(self) -> None:
        self._activate_seat()
        snap = self._start()
        inst_id = snap["instance_id"]
        resume = snap["cursor"]
        self.client.post(
            f"/instances/{inst_id}/turns",
            headers=self.login("faisal"),
            json={"text": "Second message", "client_turn_id": str(uuid.uuid4())},
        )
        blocks = _collect_sse(
            self._events_url(inst_id),
            headers={**self.login("faisal"), "Last-Event-ID": resume},
            timeout=5.0,
        )
        turn_events = [b for b in blocks if b.get("data") and b["data"].get("type") == "turn.created"]
        self.assertEqual(len(turn_events), 1)
        self.assertEqual(turn_events[0]["data"]["data"]["turn"]["blocks"][0]["text"], "Second message")
        ids_seen = {b["id"] for b in turn_events if b.get("id")}
        self.assertEqual(len(ids_seen), 1)

    def test_hidden_audience_not_delivered(self) -> None:
        self._activate_seat()
        snap = self._start()
        inst_id = snap["instance_id"]
        stream = ids.stream_instance(inst_id)

        async def _insert_buyer_only() -> None:
            url = _pg.kernel_url(self.db)
            async with await psycopg.AsyncConnection.connect(url) as conn:
                async with conn.transaction():
                    await append_outbox(
                        conn,
                        stream=stream,
                        event_type="turn.created",
                        instance_id=inst_id,
                        audience={"roles": ["buyer"]},
                        data={
                            "instance_id": inst_id,
                            "turn": {
                                "turn_id": "turn_hidden",
                                "seq": 999,
                                "author": {"kind": "system", "id": "kernel", "name": "kernel"},
                                "blocks": [{"kind": "text", "text": "buyer secret"}],
                                "at": "2026-01-01T00:00:00+00:00",
                                "attempt_id": None,
                            },
                        },
                    )

        asyncio.run(_insert_buyer_only())
        resume = snap["cursor"]
        blocks = _collect_sse(
            self._events_url(inst_id),
            headers={**self.login("faisal"), "Last-Event-ID": resume},
            timeout=3.0,
        )
        texts = [
            b["data"]["data"]["turn"]["blocks"][0]["text"]
            for b in blocks
            if b.get("data") and b["data"].get("type") == "turn.created"
        ]
        self.assertNotIn("buyer secret", texts)

    def test_heartbeat_within_interval(self) -> None:
        self._activate_seat()
        snap = self._start()
        inst_id = snap["instance_id"]
        blocks = _collect_sse(
            self._events_url(inst_id),
            headers={**self.login("faisal"), "Last-Event-ID": snap["cursor"]},
            timeout=1.0,
        )
        self.assertTrue(any(b.get("comment") == "heartbeat" for b in blocks))

    def test_delta_without_sse_id_resume_still_works(self) -> None:
        self._activate_seat()
        snap = self._start()
        inst_id = snap["instance_id"]
        resume = snap["cursor"]
        hub = self.app.state.hub
        live_blocks: list[dict[str, Any]] = []

        def _reader() -> None:
            live_blocks.extend(
                _collect_sse(
                    self._events_url(inst_id),
                    headers={**self.login("faisal"), "Last-Event-ID": resume},
                    timeout=4.0,
                    max_blocks=4,
                )
            )

        reader = threading.Thread(target=_reader, daemon=True)
        reader.start()
        time.sleep(0.6)

        async def _delta() -> None:
            await hub.publish_delta(
                instance_id=inst_id,
                turn_id="turn_stream_test",
                delta_seq=1,
                text="partial reply",
                recipient_person_id="faisal",
            )

        asyncio.run(_delta())
        reader.join(timeout=10.0)
        deltas = [b for b in live_blocks if b.get("event") == "agent.message.delta"]
        self.assertEqual(len(deltas), 1)
        self.assertIsNone(deltas[0]["id"])
        self.assertEqual(deltas[0]["data"]["data"]["text"], "partial reply")

        after = _collect_sse(
            self._events_url(inst_id),
            headers={**self.login("faisal"), "Last-Event-ID": resume},
            timeout=1.5,
        )
        self.assertFalse(
            any(b.get("data") and b["data"].get("type") == "snapshot.required" for b in after),
            "reconnect with last outbox cursor should not force snapshot",
        )

    def test_participant_removed_closes_stream(self) -> None:
        self._activate_seat()
        snap = self._start()
        inst_id = snap["instance_id"]
        stream = ids.stream_instance(inst_id)

        async def _push_after_removal() -> None:
            url = _pg.kernel_url(self.db)
            async with await psycopg.AsyncConnection.connect(url) as conn:
                async with conn.transaction():
                    await append_outbox(
                        conn,
                        stream=stream,
                        event_type="turn.created",
                        instance_id=inst_id,
                        audience={"roles": ["requester"]},
                        data={
                            "instance_id": inst_id,
                            "turn": {
                                "turn_id": "turn_after_removal",
                                "seq": 1000,
                                "author": {"kind": "system", "id": "kernel", "name": "kernel"},
                                "blocks": [{"kind": "text", "text": "should not arrive"}],
                                "at": "2026-01-01T00:00:00+00:00",
                                "attempt_id": None,
                            },
                        },
                    )

        def _background() -> None:
            time.sleep(0.4)
            _pg.admin_sql(
                self.db,
                f"delete from work.participants where instance_id = '{inst_id}' and person_id = 'faisal'",
            )
            asyncio.run(_push_after_removal())

        threading.Thread(target=_background, daemon=True).start()
        blocks = _collect_sse(
            self._events_url(inst_id),
            headers={**self.login("faisal"), "Last-Event-ID": snap["cursor"]},
            timeout=2.5,
        )
        texts = [
            b["data"]["data"]["turn"]["blocks"][0]["text"]
            for b in blocks
            if b.get("data") and b["data"].get("type") == "turn.created"
        ]
        self.assertNotIn("should not arrive", texts)


if __name__ == "__main__":
    unittest.main()
