"""FastAPI application entry point.

    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import asyncio
import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# asyncpg needs the selector event loop on Windows
if sys.platform == "win32":  # pragma: no cover - windows only
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from app.config import get_settings as load_settings
from app.db import SessionLocal, dispose_engine, init_db
from app.monitor import monitor
from app.routers import alerts, devices, readings, settings, stats, stream
from app.seed import backfill_history, readings_count, seed_devices

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
)
log = logging.getLogger("energy.main")

app_settings = load_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("bootstrapping database schema (PostgreSQL) …")
    await init_db()

    async with SessionLocal() as session:
        await seed_devices(session)
        if await readings_count(session) == 0 or app_settings.seed_history_hours > 0:
            result = await backfill_history(
                session,
                hours=app_settings.seed_history_hours,
                step_seconds=app_settings.seed_history_step_seconds,
            )
            log.info("seed: %s", result)

    await monitor.start()
    log.info("%s ready", app_settings.app_name)
    yield
    await monitor.stop()
    await dispose_engine()


app = FastAPI(
    title=app_settings.app_name,
    version=app_settings.app_version,
    description=(
        "Smart home energy usage monitor. "
        "FastAPI + WebSocket streams simulated smart-plug readings (PostgreSQL) "
        "and raises scored usage alerts."
    ),
    lifespan=lifespan,
    docs_url="/docs",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=app_settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(devices.router, prefix=app_settings.api_prefix)
app.include_router(readings.router, prefix=app_settings.api_prefix)
app.include_router(alerts.router, prefix=app_settings.api_prefix)
app.include_router(stats.router, prefix=app_settings.api_prefix)
app.include_router(settings.router, prefix=app_settings.api_prefix)
app.include_router(stream.router, prefix=app_settings.api_prefix)


@app.get("/", tags=["meta"], summary="Service banner")
async def root() -> dict:
    return {
        "name": app_settings.app_name,
        "version": app_settings.app_version,
        "docs": "/docs",
        "websocket": f"{app_settings.api_prefix}/ws/live",
    }


@app.get("/health", tags=["meta"], summary="Liveness probe")
async def health() -> dict:
    return {"status": "ok", "monitor_running": monitor.running, "ticks": monitor.ticks}
