"""Dashboard KPIs and energy breakdowns."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import get_app_settings, start_of_day, utcnow
from app.models import Device
from app.schemas import DeviceEnergy, HouseholdStats
from app.stats_service import device_stats, energy_by_device, household_stats

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("/overview", response_model=HouseholdStats, summary="Live KPI block")
async def overview(session: AsyncSession = Depends(get_session)) -> HouseholdStats:
    cfg = await get_app_settings(session)
    now = utcnow()
    devices = list(
        (await session.execute(select(Device).where(Device.active.is_(True)))).scalars().all()
    )
    stats = await device_stats(session, [d.id for d in devices], cfg, now)
    return HouseholdStats(**(await household_stats(session, cfg, now, devices, stats)))


@router.get("/energy-by-device", response_model=list[DeviceEnergy], summary="kWh per device today")
async def energy_breakdown(session: AsyncSession = Depends(get_session)) -> list[DeviceEnergy]:
    now = utcnow()
    devices = list((await session.execute(select(Device).order_by(Device.name))).scalars().all())
    if not devices:
        return []
    kwh = await energy_by_device(session, [d.id for d in devices], now)
    total = sum(kwh.values()) or 1.0
    rows = [
        DeviceEnergy(
            device_id=d.id,
            device_name=d.name,
            room=d.room,
            kwh=round(kwh.get(d.id, 0.0), 3),
            share_pct=round(kwh.get(d.id, 0.0) / total * 100.0, 1),
        )
        for d in devices
    ]
    return sorted(rows, key=lambda r: r.kwh, reverse=True)


@router.get("/history-bounds", summary="Oldest / newest reading timestamps")
async def history_bounds(session: AsyncSession = Depends(get_session)) -> dict:
    from sqlalchemy import func

    from app.models import Reading

    row = (
        await session.execute(
            select(func.min(Reading.ts), func.max(Reading.ts), func.count()).select_from(Reading)
        )
    ).one()
    return {"oldest": row[0], "newest": row[1], "readings": int(row[2] or 0)}


@router.get("/day-start")
async def day_start() -> dict:
    return {"day_start": start_of_day(utcnow())}


@router.get("/ping")
async def ping(echo: str = Query(default="pong")) -> dict:
    return {"echo": echo}
