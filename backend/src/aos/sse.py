"""SSE outbox hub: LISTEN/NOTIFY, cursor resume, delta relay (M1-BE-04 B).

**Single-process assumption:** Postgres ``LISTEN`` wakeups and in-memory ``agent.message.delta`` relay live in
this process only. Run one API worker per kernel (or accept missed live wakeups until reconnect catch-up).
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any

import psycopg
from psycopg_pool import AsyncConnectionPool

from .kernel import ids, streaming
from .kernel.outbox import OUTBOX_CHANNEL

log = logging.getLogger(__name__)

SUBSCRIBER_QUEUE_MAX = 64
LISTEN_RECONNECT_MIN = 0.5
LISTEN_RECONNECT_MAX = 30.0


def format_sse_outbox(event: dict[str, Any]) -> str:
    return f"id: {event['id']}\ndata: {json.dumps(event, separators=(',', ':'))}\n\n"


def format_sse_delta(event: dict[str, Any]) -> str:
    return f"event: agent.message.delta\ndata: {json.dumps(event, separators=(',', ':'))}\n\n"


def format_sse_comment(text: str = "heartbeat") -> str:
    return f": {text}\n\n"


@dataclass
class Subscriber:
    stream: str
    person_id: str
    org_id: str
    instance_id: str
    last_delivered_seq: int
    queue: asyncio.Queue[str | None] = field(default_factory=lambda: asyncio.Queue(maxsize=SUBSCRIBER_QUEUE_MAX))
    closed: bool = False

    def try_push(self, chunk: str) -> bool:
        if self.closed:
            return False
        try:
            self.queue.put_nowait(chunk)
            return True
        except asyncio.QueueFull:
            self.closed = True
            try:
                self.queue.put_nowait(None)
            except asyncio.QueueFull:
                pass
            return False


class OutboxHub:
    def __init__(self, database_url: str, *, heartbeat_seconds: float = 15.0) -> None:
        self._database_url = database_url
        self.heartbeat_seconds = heartbeat_seconds
        self._pool: AsyncConnectionPool | None = None
        self._subs: dict[str, list[Subscriber]] = {}
        self._subs_lock = asyncio.Lock()
        self._stop = asyncio.Event()
        self._listen_task: asyncio.Task[None] | None = None
        self._stream_locks: dict[str, asyncio.Lock] = {}

    async def start(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool
        self._stop.clear()
        self._listen_task = asyncio.create_task(self._listen_loop(), name="outbox-listen")

    async def stop(self) -> None:
        self._stop.set()
        if self._listen_task is not None:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
            self._listen_task = None
        async with self._subs_lock:
            for subs in self._subs.values():
                for sub in subs:
                    sub.closed = True
            self._subs.clear()

    async def subscribe_and_wait(self, sub: Subscriber) -> Callable[[], None]:
        async with self._subs_lock:
            self._subs.setdefault(sub.stream, []).append(sub)

        def unsubscribe() -> None:
            sub.closed = True

            async def _remove() -> None:
                async with self._subs_lock:
                    lst = self._subs.get(sub.stream, [])
                    if sub in lst:
                        lst.remove(sub)
                    if not lst:
                        self._subs.pop(sub.stream, None)

            asyncio.get_running_loop().create_task(_remove())

        return unsubscribe

    async def publish_delta(
        self,
        *,
        instance_id: str,
        turn_id: str,
        delta_seq: int,
        text: str,
        recipient_person_id: str,
    ) -> None:
        event = streaming.message_delta_event(
            instance_id=instance_id,
            turn_id=turn_id,
            delta_seq=delta_seq,
            text=text,
        )
        chunk = format_sse_delta(event)
        stream = ids.stream_instance(instance_id)
        async with self._subs_lock:
            subs = list(self._subs.get(stream, []))
        for sub in subs:
            if sub.closed or sub.person_id != recipient_person_id:
                continue
            if not sub.try_push(chunk):
                await self._remove_subscriber(sub)

    async def _remove_subscriber(self, sub: Subscriber) -> None:
        sub.closed = True
        async with self._subs_lock:
            lst = self._subs.get(sub.stream, [])
            if sub in lst:
                lst.remove(sub)
            if not lst:
                self._subs.pop(sub.stream, None)

    def _stream_lock(self, stream: str) -> asyncio.Lock:
        if stream not in self._stream_locks:
            self._stream_locks[stream] = asyncio.Lock()
        return self._stream_locks[stream]

    async def _listen_loop(self) -> None:
        backoff = LISTEN_RECONNECT_MIN
        while not self._stop.is_set():
            try:
                async with await psycopg.AsyncConnection.connect(self._database_url, autocommit=True) as conn:
                    await conn.execute(f"listen {OUTBOX_CHANNEL}")
                    backoff = LISTEN_RECONNECT_MIN
                    await self._catch_up_all_streams()
                    async for notify in conn.notifies():
                        if self._stop.is_set():
                            break
                        if notify.payload:
                            await self._dispatch_stream(notify.payload)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("LISTEN connection lost; reconnecting")
            if self._stop.is_set():
                break
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, LISTEN_RECONNECT_MAX)

    async def _catch_up_all_streams(self) -> None:
        async with self._subs_lock:
            streams = list(self._subs.keys())
        for stream in streams:
            await self._dispatch_stream(stream)

    async def _dispatch_stream(self, stream: str) -> None:
        assert self._pool is not None
        async with self._stream_lock(stream):
            async with self._subs_lock:
                subs = [s for s in self._subs.get(stream, []) if not s.closed]
            if not subs:
                return
            min_seq = min(s.last_delivered_seq for s in subs)
            async with self._pool.connection() as conn:
                rows = await streaming.fetch_outbox_after(conn, stream, min_seq)
            for sub in subs:
                if sub.closed:
                    continue
                await self._deliver_rows_to_subscriber(sub, rows)

    async def _deliver_rows_to_subscriber(
        self,
        sub: Subscriber,
        rows: list[tuple[str, int, str, str | None, dict[str, Any], dict[str, Any], Any]],
    ) -> None:
        assert self._pool is not None
        if sub.closed or not rows:
            return
        pending = [r for r in rows if r[1] > sub.last_delivered_seq]
        if not pending:
            return
        async with self._pool.connection() as conn:
            roles = await streaming.participant_roles(conn, sub.instance_id, sub.person_id)
        if not roles:
            sub.closed = True
            try:
                sub.queue.put_nowait(None)
            except asyncio.QueueFull:
                pass
            await self._remove_subscriber(sub)
            return
        for stream, seq, event_type, instance_id, audience, data, created_at in pending:
            if seq <= sub.last_delivered_seq:
                continue
            if not streaming.outbox_visible(audience, person_id=sub.person_id, participant_roles=roles):
                sub.last_delivered_seq = seq
                continue
            event = streaming.outbox_row_to_ui_event(
                stream=stream,
                seq=seq,
                event_type=event_type,
                instance_id=instance_id,
                data=data,
                created_at=created_at,
            )
            if not sub.try_push(format_sse_outbox(event)):
                await self._remove_subscriber(sub)
                return
            sub.last_delivered_seq = seq


async def _fanout_catch_up(
    pool: AsyncConnectionPool,
    sub: Subscriber,
    *,
    after_seq: int,
) -> None:
    async with pool.connection() as conn:
        rows = await streaming.fetch_outbox_after(conn, sub.stream, after_seq)
    hub_rows = rows
    if not hub_rows:
        return
    async with pool.connection() as conn:
        roles = await streaming.participant_roles(conn, sub.instance_id, sub.person_id)
    if not roles:
        sub.closed = True
        try:
            sub.queue.put_nowait(None)
        except asyncio.QueueFull:
            pass
        return
    for stream, seq, event_type, instance_id, audience, data, created_at in hub_rows:
        if seq <= sub.last_delivered_seq:
            continue
        if not streaming.outbox_visible(audience, person_id=sub.person_id, participant_roles=roles):
            sub.last_delivered_seq = seq
            continue
        event = streaming.outbox_row_to_ui_event(
            stream=stream,
            seq=seq,
            event_type=event_type,
            instance_id=instance_id,
            data=data,
            created_at=created_at,
        )
        if not sub.try_push(format_sse_outbox(event)):
            sub.closed = True
            try:
                sub.queue.put_nowait(None)
            except asyncio.QueueFull:
                pass
            return
        sub.last_delivered_seq = seq


async def preflight_instance_stream(
    pool: AsyncConnectionPool,
    *,
    org_id: str,
    instance_id: str,
    person_id: str,
) -> None:
    async with pool.connection() as conn:
        cur = await conn.execute(
            "select id from work.instances where id = %s and org_id = %s",
            (instance_id, org_id),
        )
        if await cur.fetchone() is None:
            raise InstanceStreamError("not_found", 404, "Job not found", f"No instance {instance_id!r}.")
        roles = await streaming.participant_roles(conn, instance_id, person_id)
        if not roles:
            raise InstanceStreamError(
                "not_permitted",
                403,
                "Not a participant",
                "You are not part of this job.",
            )


async def instance_event_stream(
    hub: OutboxHub,
    pool: AsyncConnectionPool,
    *,
    org_id: str,
    instance_id: str,
    person_id: str,
    cursor: str | None,
) -> AsyncIterator[str]:
    stream = ids.stream_instance(instance_id)
    async with pool.connection() as conn:
        head = await streaming.stream_head(conn, stream)
        validation = await streaming.validate_instance_cursor(conn, instance_id=instance_id, cursor=cursor)
        if not validation.ok:
            reason = validation.reason or "cursor_unknown"
            snap_seq = validation.seq if reason == "gap" and validation.seq else head
            snap = streaming.snapshot_required_event(
                stream=stream,
                seq=snap_seq,
                reason=reason,
                instance_id=instance_id,
            )
            yield format_sse_outbox(snap)
            start_seq = head
        else:
            start_seq = validation.seq

    sub = Subscriber(
        stream=stream,
        person_id=person_id,
        org_id=org_id,
        instance_id=instance_id,
        last_delivered_seq=start_seq,
    )
    unsubscribe = await hub.subscribe_and_wait(sub)
    async with hub._stream_lock(stream):
        await _fanout_catch_up(pool, sub, after_seq=start_seq)

    try:
        while not sub.closed:
            try:
                chunk = await asyncio.wait_for(sub.queue.get(), timeout=hub.heartbeat_seconds)
            except TimeoutError:
                async with pool.connection() as conn:
                    roles = await streaming.participant_roles(conn, instance_id, person_id)
                if not roles:
                    break
                yield format_sse_comment()
                continue
            if chunk is None:
                break
            yield chunk
    finally:
        unsubscribe()


class InstanceStreamError(Exception):
    def __init__(self, code: str, status: int, title: str, detail: str = "") -> None:
        self.code = code
        self.status = status
        self.title = title
        self.detail = detail
        super().__init__(title)
