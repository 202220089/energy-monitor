"""Shared dependencies and small helpers."""

from __future__ import annotations

from datetime import datetime, time, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AppSettings

SETTINGS_ID = 1


async def get_app_settings(session: AsyncSession) -> AppSettings:
    """Return the singleton settings row, creating it with defaults if needed."""
    result = await session.execute(select(AppSettings).where(AppSettings.id == SETTINGS_ID))
    cfg = result.scalar_one_or_none()
    if cfg is None:
        cfg = AppSettings(id=SETTINGS_ID)
        session.add(cfg)
        await session.commit()
        await session.refresh(cfg)
    return cfg


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def start_of_day(now: datetime) -> datetime:
    local = now.astimezone()
    return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def elapsed_hours(now: datetime) -> float:
    return max(0.25, (now - start_of_day(now)).total_seconds() / 3600.0)


def as_utc_naive(value: datetime) -> datetime:
    return value.astimezone(timezone.utc).replace(tzinfo=None)


__all__ = [
    "SETTINGS_ID",
    "as_utc_naive",
    "elapsed_hours",
    "get_app_settings",
    "start_of_day",
    "time",
    "utcnow",
]
