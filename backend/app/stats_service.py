"""Aggregation helpers shared by the WebSocket stream and the REST endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import elapsed_hours, start_of_day
from app.models import AppSettings, Device, Reading, UsageAlert


@dataclass(slots=True)
class DeviceStat:
    device_id: int
    avg_watts: float | None
    std_watts: float | None
    samples: int
    kwh_today: float
    on_minutes: float


async def device_stats(
    session: AsyncSession,
    device_ids: list[int],
    cfg: AppSettings,
    now: datetime,
) -> dict[int, DeviceStat]:
    cfg_tick = cfg.tick_seconds
    """Rolling baseline + today's energy + current ON streak for every device."""
    if not device_ids:
        return {}

    window_start = now - timedelta(minutes=cfg.baseline_window_minutes)
    day_start = start_of_day(now)
    elapsed_s = max(1.0, (now - day_start).total_seconds())

    # 1) rolling statistics of the ON samples -------------------------------
    base_rows = (
        await session.execute(
            select(
                Reading.device_id,
                func.count().label("n"),
                func.avg(Reading.watts).label("mean"),
                func.stddev_samp(Reading.watts).label("std"),
            )
            .where(
                Reading.device_id.in_(device_ids),
                Reading.is_on.is_(True),
                Reading.ts >= window_start,
                Reading.ts <= now,
            )
            .group_by(Reading.device_id)
        )
    ).all()
    baselines = {
        int(did): (int(n or 0), float(mean or 0.0), float(std or 0.0))
        for did, n, mean, std in base_rows
    }

    # 2) start of the current ON streak (last OFF sample) --------------------
    off_rows = (
        await session.execute(
            select(Reading.device_id, func.max(Reading.ts))
            .where(
                Reading.device_id.in_(device_ids),
                Reading.is_on.is_(False),
                Reading.ts <= now,
            )
            .group_by(Reading.device_id)
        )
    ).all()
    off_marks = {int(did): ts for did, ts in off_rows if ts is not None}

    # 3) energy consumed since midnight --------------------------------------
    energy_rows = (
        await session.execute(
            select(
                Reading.device_id,
                func.sum(Reading.watts).label("total"),
                func.count().label("n"),
                func.min(Reading.ts).label("first"),
                func.max(Reading.ts).label("last"),
            )
            .where(Reading.device_id.in_(device_ids), Reading.ts >= day_start)
            .group_by(Reading.device_id)
        )
    ).all()
    # energy = sum(watts) * average_sample_interval / 3.6e6
    energy = {}
    for did, total, n, first, last in energy_rows:
        n = int(n or 1)
        span = (last - first).total_seconds() if first and last and n > 1 else 0.0
        step = span / max(1, n - 1) if n > 1 else float(cfg_tick or 2.0)
        energy[int(did)] = float(total or 0.0) * step / 3_600_000.0

    stats: dict[int, DeviceStat] = {}
    for did in device_ids:
        n, mean, std = baselines.get(did, (0, 0.0, 0.0))
        since = off_marks.get(did)
        on_minutes = 0.0
        if since is not None:
            on_minutes = max(0.0, (now - since).total_seconds() / 60.0)
        stats[did] = DeviceStat(
            device_id=did,
            avg_watts=round(mean, 2) if n else None,
            std_watts=round(std, 2) if n else None,
            samples=n,
            kwh_today=round(energy.get(did, 0.0), 4),
            on_minutes=round(on_minutes, 1),
        )
    return stats


async def household_stats(
    session: AsyncSession,
    cfg: AppSettings,
    now: datetime,
    devices: list[Device],
    stats: dict[int, DeviceStat],
) -> dict:
    """KPI block: current load, energy today, projection, open alerts…"""
    total_watts = sum(d.last_watts for d in devices)
    kwh_today = sum(s.kwh_today for s in stats.values())
    hours = elapsed_hours(now)
    projected = kwh_today / hours * 24.0

    open_alerts = (
        await session.execute(
            select(func.count())
            .select_from(UsageAlert)
            .where(UsageAlert.acknowledged.is_(False))
        )
    ).scalar_one()
    critical_alerts = (
        await session.execute(
            select(func.count())
            .select_from(UsageAlert)
            .where(
                UsageAlert.acknowledged.is_(False),
                UsageAlert.severity.in_(("high", "critical")),
            )
        )
    ).scalar_one()

    devices_on = sum(1 for d in devices if d.is_on)

    return {
        "total_watts": round(total_watts, 1),
        "budget_watts": cfg.household_budget_watts,
        "budget_used_pct": round(
            (total_watts / cfg.household_budget_watts * 100.0) if cfg.household_budget_watts else 0.0,
            1,
        ),
        "devices_online": sum(1 for d in devices if d.active),
        "devices_on": devices_on,
        "devices_total": len(devices),
        "kwh_today": round(kwh_today, 3),
        "kwh_budget": cfg.daily_budget_kwh,
        "projected_kwh_today": round(projected, 3),
        "cost_today": round(kwh_today * cfg.price_per_kwh, 2),
        "price_per_kwh": cfg.price_per_kwh,
        "currency": cfg.currency,
        "open_alerts": int(open_alerts),
        "critical_alerts": int(critical_alerts),
        "ts": now,
    }


async def energy_by_device(
    session: AsyncSession, device_ids: list[int], now: datetime
) -> list[dict]:
    day_start = start_of_day(now)
    elapsed_s = max(1.0, (now - day_start).total_seconds())
    rows = (
        await session.execute(
            select(
                Reading.device_id,
                func.sum(Reading.watts).label("total"),
                func.count().label("n"),
                func.min(Reading.ts).label("first"),
                func.max(Reading.ts).label("last"),
            )
            .where(Reading.device_id.in_(device_ids), Reading.ts >= day_start)
            .group_by(Reading.device_id)
        )
    ).all()
    kwh = {}
    for did, total, n, first, last in rows:
        n = int(n or 1)
        span = (last - first).total_seconds() if first and last and n > 1 else 0.0
        step = span / max(1, n - 1) if n > 1 else 2.0
        kwh[int(did)] = float(total or 0.0) * step / 3_600_000.0
    return kwh
