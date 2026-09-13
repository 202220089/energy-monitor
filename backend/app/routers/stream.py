"""WebSocket live stream (Day 1 of the brief).

`/api/ws/live` pushes:
  * a ``snapshot`` frame on connect (current device states + KPIs + recent alerts)
  * a ``tick`` frame on every simulator cycle with fresh readings and any new alerts
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.db import SessionLocal
from app.deps import get_app_settings, utcnow
from app.models import Device, UsageAlert
from app.schemas import AlertOut, HouseholdStats
from app.stats_service import device_stats, household_stats
from app.ws import manager

log = logging.getLogger("energy.stream")

router = APIRouter(prefix="/ws", tags=["stream"])


async def build_snapshot() -> dict:
    """Full initial state so a newly opened dashboard renders instantly."""
    async with SessionLocal() as session:
        cfg = await get_app_settings(session)
        now = utcnow()
        devices = list(
            (await session.execute(select(Device).where(Device.active.is_(True)).order_by(Device.id)))
            .scalars()
            .all()
        )
        stats = await device_stats(session, [d.id for d in devices], cfg, now)
        household = await household_stats(session, cfg, now, devices, stats)

        live = []
        from app.monitor import EnergyMonitor  # local import avoids a cycle

        live = EnergyMonitor._build_live(devices, stats, cfg, now, [])

        recent = list(
            (
                await session.execute(
                    select(UsageAlert).order_by(UsageAlert.created_at.desc()).limit(12)
                )
            )
            .scalars()
            .all()
        )
        names = {d.id: d.name for d in devices}
        recent_alerts = [
            AlertOut.model_validate(alert, from_attributes=True).model_copy(
                update={"device_name": names.get(alert.device_id)}
            )
            for alert in recent
        ]

        return {
            "type": "snapshot",
            "ts": now.isoformat(),
            "household": HouseholdStats(**household).model_dump(mode="json"),
            "devices": [d.model_dump(mode="json") for d in live],
            "recent_alerts": [a.model_dump(mode="json") for a in recent_alerts],
        }


@router.websocket("/live")
async def live_stream(websocket: WebSocket) -> None:
    await manager.connect(websocket)
    try:
        await manager.send(websocket, await build_snapshot())
        while True:
            raw = await websocket.receive_text()
            if raw.strip() == "ping":
                await manager.send(websocket, {"type": "pong"})
    except WebSocketDisconnect:
        pass
    except Exception:  # pragma: no cover - defensive
        log.exception("websocket error")
    finally:
        manager.disconnect(websocket)
