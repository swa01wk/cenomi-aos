"""Stream reply text deltas to the kernel."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from .errors import Fenced
from .protocol import AttemptContext

_FLUSH_INTERVAL_S = 0.25
_FLUSH_CHARS = 200


async def stream_text_deltas(
    ctx: AttemptContext,
    *,
    turn_id: str,
    seq_start: int,
    chunks: list[str],
) -> tuple[int, str]:
    """Post batched stream deltas; return (next_seq, full_text)."""
    seq = seq_start
    buf = ""
    last_flush = time.monotonic()
    full = ""

    async def flush(force: bool = False) -> None:
        nonlocal buf, seq, last_flush
        if not buf:
            return
        if not force and len(buf) < _FLUSH_CHARS and (time.monotonic() - last_flush) < _FLUSH_INTERVAL_S:
            return
        try:
            await ctx.post_events(stream=[{"turn_id": turn_id, "seq": seq, "text": buf}])
        except Fenced:
            raise
        seq += 1
        buf = ""
        last_flush = time.monotonic()

    for chunk in chunks:
        ctx.check()
        buf += chunk
        full += chunk
        await flush(force=False)
    await flush(force=True)
    return seq, full
