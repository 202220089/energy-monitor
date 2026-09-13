"""Anomaly detection engine (Day 2 of the brief).

Three rules, each scored 0-100 by *how far* the observation is from normal:

1. ``spike``           - the device draws way more power than its own rolling
                         average.  Implemented as a z-score against the rolling
                         window of ON samples (``avg`` / ``stddev_samp``), so a
                         device merely switching on is not an anomaly but a
                         fridge suddenly pulling 3x is.
2. ``on_too_long``     - the device has been running continuously for longer
                         than ``max_on_minutes``.
3. ``household_budget``- the total household load crosses the configured
                         budget (watts).
4. ``daily_energy``    - the projected energy for today crosses ``daily_budget_kwh``.

Every rule is de-duplicated with a per (device, rule) cooldown so a single
incident produces one alert instead of one per tick.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import start_of_day
from app.models import AlertRule, AlertSeverity, AppSettings, Reading, UsageAlert


# --------------------------------------------------------------------------- io


@dataclass(slots=True)
class Sample:
    device_id: int
    device_name: str
    watts: float
    is_on: bool


@dataclass(slots=True)
class Baseline:
    mean: float
    std: float
    n: int


def severity_for(score: float) -> AlertSeverity:
    if score >= 90:
        return AlertSeverity.CRITICAL
    if score >= 80:
        return AlertSeverity.HIGH
    if score >= 65:
        return AlertSeverity.MEDIUM
    return AlertSeverity.LOW


def score_from_excess(relative_excess: float) -> float:
    """Map "how far past the threshold" onto a 50..100 score.

    ``relative_excess`` is expressed as a fraction of the threshold, e.g. a load
    25 % above the budget is ``0.25``.  Reaching the threshold is already
    abnormal, so the floor is 50 and the curve saturates at 2x the threshold.
    """
    relative_excess = max(0.0, relative_excess)
    return round(min(100.0, 50.0 + 50.0 * (1.0 - math.exp(-relative_excess))), 1)


class AlertEngine:
    """Stateless (DB-driven) detector evaluated once per simulator tick."""

    def __init__(self) -> None:
        self._last_tick: datetime | None = None

    # ---------------------------------------------------------------- queries
    @staticmethod
    async def _baselines(
        session: AsyncSession, device_ids: list[int], start: datetime, end: datetime
    ) -> dict[int, Baseline]:
        """Rolling mean / stddev of ON samples per device (one grouped query)."""
        if not device_ids:
            return {}
        stmt: Select = (
            select(
                Reading.device_id,
                func.count().label("n"),
                func.avg(Reading.watts).label("mean"),
                func.stddev_samp(Reading.watts).label("std"),
            )
            .where(
                Reading.device_id.in_(device_ids),
                Reading.is_on.is_(True),
                Reading.ts >= start,
                Reading.ts < end,
            )
            .group_by(Reading.device_id)
        )
        rows = (await session.execute(stmt)).all()
        out: dict[int, Baseline] = {}
        for device_id, n, mean, std in rows:
            out[device_id] = Baseline(
                mean=float(mean or 0.0), std=float(std or 0.0), n=int(n or 0)
            )
        return out

    @staticmethod
    async def _streak_starts(
        session: AsyncSession, device_ids: list[int], now: datetime
    ) -> dict[int, datetime]:
        """Timestamp of the last OFF sample -> start of the current ON streak."""
        if not device_ids:
            return {}
        stmt = (
            select(Reading.device_id, func.max(Reading.ts))
            .where(Reading.device_id.in_(device_ids), Reading.is_on.is_(False), Reading.ts <= now)
            .group_by(Reading.device_id)
        )
        rows = (await session.execute(stmt)).all()
        return {int(did): ts for did, ts in rows if ts is not None}

    @staticmethod
    async def _last_alert_times(
        session: AsyncSession, device_ids: list[int], since: datetime
    ) -> dict[tuple[int, str], datetime]:
        """Most recent firing time per (device_id, rule)."""
        if not device_ids:
            return {}
        stmt = (
            select(UsageAlert.device_id, UsageAlert.rule, func.max(UsageAlert.created_at))
            .where(
                UsageAlert.device_id.in_(device_ids),
                UsageAlert.created_at >= since,
            )
            .group_by(UsageAlert.device_id, UsageAlert.rule)
        )
        rows = (await session.execute(stmt)).all()
        return {(int(did), rule): ts for did, rule, ts in rows if did is not None}

    @staticmethod
    async def _household_cooldown(session: AsyncSession, since: datetime) -> set[str]:
        stmt = (
            select(UsageAlert.rule)
            .where(UsageAlert.device_id.is_(None), UsageAlert.created_at >= since)
            .distinct()
        )
        rows = (await session.execute(stmt)).all()
        return {rule for (rule,) in rows}

    # ---------------------------------------------------------------- evaluate
    async def evaluate(
        self,
        session: AsyncSession,
        settings: AppSettings,
        now: datetime,
        samples: list[Sample],
        device_created: dict[int, datetime],
        energy_today_kwh: float,
        projected_kwh: float,
    ) -> list[UsageAlert]:
        """Run every rule and return the freshly created (uncommitted) alerts."""
        if not samples:
            return []

        device_ids = [s.device_id for s in samples]
        window = timedelta(minutes=settings.baseline_window_minutes)
        cooldown = timedelta(seconds=settings.alert_cooldown_seconds)

        on_long_cooldown = timedelta(minutes=max(60.0, settings.max_on_minutes * 1.5))
        lookback = max(cooldown, on_long_cooldown)
        baselines = await self._baselines(session, device_ids, now - window, now)
        streak_starts = await self._streak_starts(session, device_ids, now)
        last_fired = await self._last_alert_times(session, device_ids, now - lookback)
        household_cooling = await self._household_cooldown(session, now - cooldown)

        def cooled_down(key: tuple[int, str], rule_cooldown: timedelta) -> bool:
            last = last_fired.get(key)
            return last is None or (now - last) > rule_cooldown

        alerts: list[UsageAlert] = []
        total_watts = 0.0

        for sample in samples:
            total_watts += sample.watts

            # ---------------------------------------------------- rule 1: spike
            if sample.is_on and cooled_down(
                (sample.device_id, AlertRule.SPIKE.value), cooldown
            ):
                base = baselines.get(sample.device_id)
                if base and base.n >= settings.min_baseline_samples and base.mean > 0:
                    std_eff = max(base.std, base.mean * 0.05, 1.0)
                    z = (sample.watts - base.mean) / std_eff
                    if z >= settings.z_threshold:
                        excess = (z - settings.z_threshold) / settings.z_threshold
                        score = score_from_excess(excess)
                        alerts.append(
                            UsageAlert(
                                device_id=sample.device_id,
                                rule=AlertRule.SPIKE.value,
                                severity=severity_for(score).value,
                                score=score,
                                message=(
                                    f"{sample.device_name} is drawing {sample.watts:,.0f} W - "
                                    f"z={z:.1f} above its {settings.baseline_window_minutes}-min "
                                    f"average of {base.mean:,.0f} W."
                                ),
                                value=round(sample.watts, 2),
                                baseline=round(base.mean, 2),
                                threshold=settings.z_threshold,
                                deviation=round(z, 2),
                                created_at=now,
                            )
                        )

            # --------------------------------------------- rule 2: on too long
            if sample.is_on and cooled_down(
                (sample.device_id, AlertRule.ON_TOO_LONG.value), on_long_cooldown
            ):
                start = streak_starts.get(sample.device_id) or device_created.get(
                    sample.device_id, now
                )
                on_minutes = max(0.0, (now - start).total_seconds() / 60.0)
                if on_minutes >= settings.max_on_minutes:
                    excess = (on_minutes - settings.max_on_minutes) / settings.max_on_minutes
                    score = score_from_excess(excess)
                    alerts.append(
                        UsageAlert(
                            device_id=sample.device_id,
                            rule=AlertRule.ON_TOO_LONG.value,
                            severity=severity_for(score).value,
                            score=score,
                            message=(
                                f"{sample.device_name} has been ON for {on_minutes:,.0f} min "
                                f"(limit {settings.max_on_minutes:,.0f} min)."
                            ),
                            value=round(on_minutes, 1),
                            baseline=settings.max_on_minutes,
                            threshold=settings.max_on_minutes,
                            deviation=round(excess * 100, 1),
                            created_at=now,
                        )
                    )

        # ----------------------------------------- rule 3: household load budget
        if (
            total_watts > settings.household_budget_watts
            and AlertRule.HOUSEHOLD_BUDGET.value not in household_cooling
        ):
            excess = (total_watts - settings.household_budget_watts) / settings.household_budget_watts
            score = score_from_excess(excess)
            alerts.append(
                UsageAlert(
                    device_id=None,
                    rule=AlertRule.HOUSEHOLD_BUDGET.value,
                    severity=severity_for(score).value,
                    score=score,
                    message=(
                        f"Household load {total_watts:,.0f} W exceeded the "
                        f"{settings.household_budget_watts:,.0f} W budget by "
                        f"{excess * 100:.0f}%."
                    ),
                    value=round(total_watts, 2),
                    baseline=settings.household_budget_watts,
                    threshold=settings.household_budget_watts,
                    deviation=round(excess * 100, 1),
                    created_at=now,
                )
            )

        # ---------------------------------------- rule 4: projected daily energy
        hours_elapsed = (now - start_of_day(now)).total_seconds() / 3600.0
        if (
            hours_elapsed >= 6
            and projected_kwh > settings.daily_budget_kwh
            and AlertRule.DAILY_ENERGY.value not in household_cooling
        ):
            excess = (projected_kwh - settings.daily_budget_kwh) / settings.daily_budget_kwh
            score = score_from_excess(excess)
            alerts.append(
                UsageAlert(
                    device_id=None,
                    rule=AlertRule.DAILY_ENERGY.value,
                    severity=severity_for(score).value,
                    score=score,
                    message=(
                        f"Projected daily consumption {projected_kwh:.1f} kWh is above the "
                        f"{settings.daily_budget_kwh:.1f} kWh budget "
                        f"({hours_elapsed:.1f} h elapsed today)."
                    ),
                    value=round(projected_kwh, 3),
                    baseline=settings.daily_budget_kwh,
                    threshold=settings.daily_budget_kwh,
                    deviation=round(excess * 100, 1),
                    created_at=now,
                )
            )

        return alerts


alert_engine = AlertEngine()

