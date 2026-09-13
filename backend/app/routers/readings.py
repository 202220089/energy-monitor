"""Raw readings + down-sampled time series for the charts."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import utcnow
from app.models import Device, Reading
from app.schemas import ReadingOut, SeriesOut, SeriesPoint

router = APIRouter(prefix="/readings", tags=["readings"])

_WINDOW_RE = re.compile(r"^(\d+)(m|h|d)$")


def parse_window(window: str) -> timedelta:
    match = _WINDOW_RE.match(window.strip().lower())
    if not match:
        raise HTTPException(status_code=400, detail="window must look like 30m, 6h or 7d")
    amount, unit = int(match.group(1)), match.group(2)
    seconds = {"m": 60, "h": 3600, "d": 86400}[unit]
    return timedelta(seconds=amount * seconds)


@router.get("", response_model=list[ReadingOut], summary="Raw readings (paged, newest first)")
async def list_readings(
    device_id: int | None = Query(default=None),
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=5000),
    session: AsyncSession = Depends(get_session),
) -> list[Reading]:
    stmt: Select = select(Reading).order_by(Reading.ts.desc()).limit(limit)
    if device_id is not None:
        stmt = stmt.where(Reading.device_id == device_id)
    if start is not None:
        stmt = stmt.where(Reading.ts >= start)
    if end is not None:
        stmt = stmt.where(Reading.ts <= end)
    return list((await session.execute(stmt)).scalars().all())


@router.get("/series", response_model=SeriesOut, summary="Down-sampled series for the charts")
async def series(
    device_id: int | None = Query(default=None, description="omit for the household total"),
    window: str = Query(default="6h"),
    points: int = Query(default=120, ge=10, le=1000),
    session: AsyncSession = Depends(get_session),
) -> SeriesOut:
    delta = parse_window(window)
    end = utcnow()
    start = end - delta
    window_seconds = int(delta.total_seconds())
    bucket = max(1, window_seconds // points)

    bucket_ts = func.to_timestamp(
        func.floor(func.extract("epoch", Reading.ts) / bucket) * bucket
    ).label("bucket")

    device_name: str | None = None

    if device_id is not None:
        device = await session.get(Device, device_id)
        if not device:
            raise HTTPException(status_code=404, detail="Device not found")
        device_name = device.name
        stmt = (
            select(bucket_ts, func.avg(Reading.watts).label("watts"))
            .where(Reading.device_id == device_id, Reading.ts >= start, Reading.ts <= end)
            .group_by(bucket_ts)
            .order_by(bucket_ts)
        )
        rows = (await session.execute(stmt)).all()
        series_points = [
            SeriesPoint(ts=ts.replace(tzinfo=timezone.utc), watts=round(float(watts), 2))
            for ts, watts in rows
        ]
    else:
        # per-device average inside each bucket, summed across devices
        inner = (
            select(
                Reading.device_id.label("device_id"),
                bucket_ts.label("bucket"),
                func.avg(Reading.watts).label("watts"),
            )
            .where(Reading.ts >= start, Reading.ts <= end)
            .group_by(Reading.device_id, bucket_ts)
            .subquery()
        )
        stmt = (
            select(inner.c.bucket, func.sum(inner.c.watts).label("watts"))
            .group_by(inner.c.bucket)
            .order_by(inner.c.bucket)
        )
        rows = (await session.execute(stmt)).all()
        series_points = [
            SeriesPoint(ts=ts.replace(tzinfo=timezone.utc), watts=round(float(watts), 2))
            for ts, watts in rows
        ]

    return SeriesOut(
        device_id=device_id,
        device_name=device_name,
        bucket_seconds=bucket,
        points=series_points,
    )
