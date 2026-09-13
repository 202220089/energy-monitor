"""Tunable detection thresholds + simulator controls."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import get_app_settings
from app.monitor import monitor
from app.schemas import SettingsOut, SettingsUpdate, SimulatorStatus

router = APIRouter(tags=["settings"])


@router.get("/settings", response_model=SettingsOut, summary="Current thresholds & budgets")
async def get_settings(session: AsyncSession = Depends(get_session)) -> object:
    return await get_app_settings(session)


@router.patch("/settings", response_model=SettingsOut, summary="Update thresholds & budgets")
async def update_settings(
    payload: SettingsUpdate, session: AsyncSession = Depends(get_session)
) -> object:
    cfg = await get_app_settings(session)
    for field, value in payload.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(cfg, field, value)
    await session.commit()
    await session.refresh(cfg)
    return cfg


@router.post("/simulator/start", response_model=SimulatorStatus, summary="Start the live stream")
async def start_simulator(session: AsyncSession = Depends(get_session)) -> SimulatorStatus:
    cfg = await get_app_settings(session)
    cfg.simulator_running = True
    await session.commit()
    await monitor.start()
    return await _status(session)


@router.post("/simulator/stop", response_model=SimulatorStatus, summary="Pause the live stream")
async def stop_simulator(session: AsyncSession = Depends(get_session)) -> SimulatorStatus:
    cfg = await get_app_settings(session)
    cfg.simulator_running = False
    await session.commit()
    return await _status(session)


@router.get("/simulator/status", response_model=SimulatorStatus)
async def simulator_status(session: AsyncSession = Depends(get_session)) -> SimulatorStatus:
    return await _status(session)


async def _status(session: AsyncSession) -> SimulatorStatus:
    cfg = await get_app_settings(session)
    from sqlalchemy import func, select

    from app.models import Device

    devices = int(
        (
            await session.execute(
                select(func.count()).select_from(Device).where(Device.active.is_(True))
            )
        ).scalar_one()
    )
    return SimulatorStatus(
        running=bool(cfg.simulator_running and monitor.running),
        tick_seconds=cfg.tick_seconds,
        devices=devices,
        ticks=monitor.ticks,
    )
