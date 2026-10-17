"""Entry point: python -m aos.worker"""

from __future__ import annotations

import asyncio
import logging
import signal

from .config import load_config
from .http_client import HttpKernelClient
from .paths import schema_dir  # noqa: F401 — fail fast if schemas missing
from .runner import Worker
from .default_fake import assist_complete
from .runtime import FakeRuntime, LangGraphRuntime

log = logging.getLogger("aos.worker")


def _configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def _runtime(name: str):
    if name == "fake":
        return FakeRuntime([assist_complete])
    if name == "langgraph":
        return LangGraphRuntime()
    raise RuntimeError(f"unknown AOS_RUNTIME {name!r}")


async def _main_async() -> None:
    _ = schema_dir()
    cfg = load_config()
    if cfg.runtime == "langgraph":
        log.error(
            "AOS_RUNTIME=langgraph is not available in M1; use AOS_RUNTIME=fake until M1-AG-02 wires the graph"
        )
        raise SystemExit(1)
    client = HttpKernelClient(cfg.api_url, cfg.worker_token)
    runtime = _runtime(cfg.runtime)
    worker = Worker(
        cfg.worker_id,
        client,
        runtime,
        cfg.lanes,
        submit_shutdown_timeout_s=cfg.submit_shutdown_timeout_s,
        poll_min_s=cfg.poll_min_s,
        poll_max_s=cfg.poll_max_s,
    )

    loop = asyncio.get_running_loop()

    def _stop(*_args: object) -> None:
        worker.request_shutdown()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _stop)
        except NotImplementedError:
            signal.signal(sig, lambda *_: _stop())

    try:
        await worker.run_forever()
    except SystemExit:
        raise
    finally:
        await client.aclose()


def main() -> None:
    _configure_logging()
    try:
        asyncio.run(_main_async())
    except SystemExit as exc:
        raise SystemExit(exc.code) from None
    except RuntimeError as exc:
        log.error("%s", exc)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
