"""Stream reply text deltas to the kernel."""

from __future__ import annotations

import time

from .errors import Fenced
from .protocol import AttemptContext

_FLUSH_INTERVAL_S = 0.25
_FLUSH_CHARS = 200


class LiveStreamBatcher:
    """Batch live text chunks into POST /events stream payloads."""

    def __init__(self, ctx: AttemptContext, *, turn_id: str, seq_start: int = 0):
        self._ctx = ctx
        self._turn_id = turn_id
        self.seq = seq_start
        self._buf = ""
        self.full = ""
        self._last_flush = time.monotonic()

    async def push(self, text: str) -> None:
        if not text:
            return
        self._buf += text
        self.full += text
        await self._flush(force=False)

    async def finish(self) -> tuple[int, str]:
        await self._flush(force=True)
        return self.seq, self.full

    async def _flush(self, *, force: bool) -> None:
        if not self._buf:
            return
        if not force and len(self._buf) < _FLUSH_CHARS and (time.monotonic() - self._last_flush) < _FLUSH_INTERVAL_S:
            return
        try:
            await self._ctx.post_events(
                stream=[{"turn_id": self._turn_id, "seq": self.seq, "text": self._buf}],
            )
        except Fenced:
            raise
        self.seq += 1
        self._buf = ""
        self._last_flush = time.monotonic()
