"""Application factory and lifespan: open the pool, load the organization, seed it if asked."""

from __future__ import annotations

from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from psycopg_pool import AsyncConnectionPool

from ..kernel.org import load_org, seed_sql
from ..kernel.scheduler import start_scheduler
from ..kernel.settings import Settings
from ..sse import OutboxHub
from .deps import Kernel
from .problems import register_problem_handlers
from .routes import router


async def seed(database_url: str, sql: str) -> None:
    async with await psycopg.AsyncConnection.connect(database_url, autocommit=True) as conn:
        await conn.execute(sql)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        org = load_org(settings.org_file)
        if settings.seed_on_start:
            await seed(settings.database_url, seed_sql(org))
        pool = AsyncConnectionPool(settings.database_url, min_size=1, max_size=settings.pool_max, open=False)
        await pool.open(wait=True, timeout=15)
        hub = OutboxHub(settings.database_url, heartbeat_seconds=settings.sse_heartbeat_seconds)
        await hub.start(pool)
        app.state.kernel = Kernel(settings=settings, org=org, pool=pool)
        app.state.hub = hub
        sched_task, sched_stop = start_scheduler(pool, interval_s=settings.scheduler_interval_seconds)
        try:
            yield
        finally:
            sched_stop.set()
            await sched_task
            await hub.stop()
            await pool.close()

    app = FastAPI(title="AOS kernel", version="0.1.0-m0", lifespan=lifespan,
                  description="Lifecycle, permission and progression for AOS Seats. M0: org, packs, audit.")
    register_problem_handlers(app)
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"],
                       allow_headers=["*"])
    app.include_router(router, prefix="/api")
    if settings.web_dist and (settings.web_dist / "index.html").is_file():
        app.mount("/", StaticFiles(directory=settings.web_dist, html=True), name="web")
    return app
