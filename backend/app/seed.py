"""Database seeding: demo smart plugs + a back-filled history.

The back-fill runs the *same* detection rules over the generated past, so the
dashboard opens with meaningful rolling averages and a realistic alert history
instead of an empty screen.
"""

from __future__ import annotations

import logging
import random
import statistics
from collections import defaultdict, deque
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import elapsed_hours, get_app_settings, start_of_day, utcnow
from app.detection import score_from_excess, severity_for
from app.models import AlertRule, Device, Reading, UsageAlert
from app.simulator import simulator

log = logging.getLogger("energy.seed")

# name, category, room, nominal W, standby W, duty cycle, cycle minutes,
# spikes/hour, jitter
DEFAULT_DEVICES: list[dict] = [
    {"name": "Air Conditioner", "category": "HVAC", "room": "Living Room",
     "nominal_watts": 1600, "standby_watts": 4, "duty_cycle": 0.50, "cycle_minutes": 60,
     "spike_probability": 0.4, "jitter_pct": 0.07},
    {"name": "Refrigerator", "category": "Appliance", "room": "Kitchen",
     "nominal_watts": 180, "standby_watts": 5, "duty_cycle": 0.85, "cycle_minutes": 20,
     "spike_probability": 0.25, "jitter_pct": 0.10},
    {"name": "Washing Machine", "category": "Appliance", "room": "Laundry",
     "nominal_watts": 900, "standby_watts": 3, "duty_cycle": 0.12, "cycle_minutes": 120,
     "spike_probability": 0.7, "jitter_pct": 0.18},
    {"name": "Water Heater", "category": "Water", "room": "Bathroom",
     "nominal_watts": 2200, "standby_watts": 2, "duty_cycle": 0.30, "cycle_minutes": 180,
     "spike_probability": 0.2, "jitter_pct": 0.05},
    {"name": "Electric Oven", "category": "Cooking", "room": "Kitchen",
     "nominal_watts": 2400, "standby_watts": 2, "duty_cycle": 0.10, "cycle_minutes": 60,
     "spike_probability": 0.3, "jitter_pct": 0.06},
    {"name": "Microwave", "category": "Cooking", "room": "Kitchen",
     "nominal_watts": 1200, "standby_watts": 3, "duty_cycle": 0.08, "cycle_minutes": 30,
     "spike_probability": 0.5, "jitter_pct": 0.12},
    {"name": "Smart TV 65\"", "category": "Entertainment", "room": "Living Room",
     "nominal_watts": 130, "standby_watts": 12, "duty_cycle": 0.75, "cycle_minutes": 240,
     "spike_probability": 0.2, "jitter_pct": 0.08},
    {"name": "Desktop PC", "category": "Electronics", "room": "Office",
     "nominal_watts": 320, "standby_watts": 8, "duty_cycle": 0.65, "cycle_minutes": 300,
     "spike_probability": 0.2, "jitter_pct": 0.12},
    {"name": "Wi-Fi Router", "category": "Network", "room": "Office",
     "nominal_watts": 14, "standby_watts": 14, "duty_cycle": 1.0, "cycle_minutes": 60,
     "spike_probability": 0.1, "jitter_pct": 0.05},
    {"name": "LED Lighting", "category": "Lighting", "room": "Whole Home",
     "nominal_watts": 90, "standby_watts": 0.5, "duty_cycle": 0.60, "cycle_minutes": 40,
     "spike_probability": 0.1, "jitter_pct": 0.05},
    {"name": "EV Charger", "category": "EV", "room": "Garage",
     "nominal_watts": 3300, "standby_watts": 5, "duty_cycle": 0.18, "cycle_minutes": 240,
     "spike_probability": 0.2, "jitter_pct": 0.04},
    {"name": "Dishwasher", "category": "Appliance", "room": "Kitchen",
     "nominal_watts": 1500, "standby_watts": 3, "duty_cycle": 0.10, "cycle_minutes": 90,
     "spike_probability": 0.4, "jitter_pct": 0.14},
]


async def seed_devices(session: AsyncSession, force: bool = False) -> int:
    """Insert the demo devices if they are missing. Returns the number added."""
    existing = {
        name for (name,) in (await session.execute(select(Device.name))).all()
    }
    added = 0
    for payload in DEFAULT_DEVICES:
        if payload["name"] in existing and not force:
            continue
        if payload["name"] in existing:
            continue
        device = Device(**payload, is_on=random.random() < payload["duty_cycle"])
        session.add(device)
        added += 1
    if added:
        await session.commit()
        log.info("seeded %d devices", added)
    return added


async def readings_count(session: AsyncSession) -> int:
    return int((await session.execute(select(func.count()).select_from(Reading))).scalar_one())


async def backfill_history(
    session: AsyncSession, hours: int = 6, step_seconds: int = 30
) -> dict[str, int]:
    """Generate `hours` of readings + run the detector over them (idempotent)."""
    cfg = await get_app_settings(session)
    devices = list(
        (await session.execute(select(Device).where(Device.active.is_(True)).order_by(Device.id)))
        .scalars()
        .all()
    )
    if not devices:
        return {"readings": 0, "alerts": 0}

    expected = int(hours * 3600 / max(1, step_seconds)) * len(devices)
    current = await readings_count(session)
    if current >= expected * 0.75:
        log.info("history already present (%d readings), skipping back-fill", current)
        return {"readings": 0, "alerts": 0, "skipped": 1}

    now = utcnow().replace(second=0, microsecond=0)
    start = now - timedelta(hours=hours)
    simulator.reset()

    rows: list[Reading] = []
    ts = start
    while ts <= now:
        for device in devices:
            watts, is_on = simulator.step(device, ts, float(step_seconds))
            device.is_on = is_on
            device.last_watts = watts
            device.last_reading_at = ts
            rows.append(Reading(device_id=device.id, watts=watts, is_on=is_on, ts=ts))
        ts += timedelta(seconds=step_seconds)

    for i in range(0, len(rows), 1000):
        session.add_all(rows[i : i + 1000])
        await session.flush()
    await session.commit()
    log.info("back-filled %d readings over %d h", len(rows), hours)

    alerts = await _detect_over_history(session, cfg, start, now)
    return {"readings": len(rows), "alerts": alerts}


async def _detect_over_history(
    session: AsyncSession, cfg, start: datetime, end: datetime
) -> int:
    """Replay the rules over the freshly seeded history (pure Python, fast)."""
    window = timedelta(minutes=cfg.baseline_window_minutes)
    cooldown = timedelta(seconds=max(cfg.alert_cooldown_seconds, 5 * 60))
    on_long_cooldown = timedelta(minutes=max(60.0, cfg.max_on_minutes * 1.5))
    load_start = start - window - timedelta(minutes=5)

    rows = (
        await session.execute(
            select(Reading.device_id, Reading.watts, Reading.is_on, Reading.ts)
            .where(Reading.ts >= load_start, Reading.ts <= end)
            .order_by(Reading.ts.asc())
        )
    ).all()
    if not rows:
        return 0

    devices = {
        d.id: d
        for d in (await session.execute(select(Device))).scalars().all()
    }

    history: dict[int, deque[tuple[datetime, float]]] = defaultdict(deque)
    last_off: dict[int, datetime] = {}
    last_alert: dict[tuple[int, str], datetime] = {}
    household_last: dict[str, datetime] = {}
    energy_today: dict[int, float] = defaultdict(float)
    step_s = 30.0

    alerts: list[UsageAlert] = []
    grouped: dict[datetime, list[tuple[int, float, bool]]] = defaultdict(list)
    for device_id, watts, is_on, ts in rows:
        grouped[ts].append((int(device_id), float(watts), bool(is_on)))

    for ts in sorted(grouped):
        total = 0.0
        for device_id, watts, is_on in grouped[ts]:
            device = devices.get(device_id)
            if device is None:
                continue
            total += watts
            energy_today[device_id] += watts * step_s / 3_600_000.0

            if not is_on:
                last_off[device_id] = ts
                continue

            bucket = history[device_id]
            bucket.append((ts, watts))
            while bucket and (ts - bucket[0][0]) > window:
                bucket.popleft()

            # ---------------------------------------------------- rule 1: spike
            if len(bucket) >= cfg.min_baseline_samples:
                values = [w for _, w in bucket]
                mean = statistics.fmean(values)
                std = statistics.stdev(values) if len(values) > 1 else 0.0
                std_eff = max(std, mean * 0.05, 1.0)
                z = (watts - mean) / std_eff
                key = (device_id, AlertRule.SPIKE.value)
                if z >= cfg.z_threshold and ts - last_alert.get(key, start - cooldown) > cooldown:
                    last_alert[key] = ts
                    score = score_from_excess((z - cfg.z_threshold) / cfg.z_threshold)
                    alerts.append(
                        UsageAlert(
                            device_id=device_id,
                            rule=AlertRule.SPIKE.value,
                            severity=severity_for(score).value,
                            score=score,
                            message=(
                                f"{device.name} is drawing {watts:,.0f} W - z={z:.1f} above "
                                f"its {cfg.baseline_window_minutes}-min average of {mean:,.0f} W."
                            ),
                            value=round(watts, 2),
                            baseline=round(mean, 2),
                            threshold=cfg.z_threshold,
                            deviation=round(z, 2),
                            created_at=ts,
                        )
                    )

            # ----------------------------------------------- rule 2: on too long
            since = last_off.get(device_id) or device.created_at.replace(tzinfo=ts.tzinfo)
            on_minutes = max(0.0, (ts - since).total_seconds() / 60.0)
            key = (device_id, AlertRule.ON_TOO_LONG.value)
            if (
                on_minutes >= cfg.max_on_minutes
                and ts - last_alert.get(key, start - on_long_cooldown) > on_long_cooldown
            ):
                last_alert[key] = ts
                excess = (on_minutes - cfg.max_on_minutes) / cfg.max_on_minutes
                score = score_from_excess(excess)
                alerts.append(
                    UsageAlert(
                        device_id=device_id,
                        rule=AlertRule.ON_TOO_LONG.value,
                        severity=severity_for(score).value,
                        score=score,
                        message=(
                            f"{device.name} has been ON for {on_minutes:,.0f} min "
                            f"(limit {cfg.max_on_minutes:,.0f} min)."
                        ),
                        value=round(on_minutes, 1),
                        baseline=cfg.max_on_minutes,
                        threshold=cfg.max_on_minutes,
                        deviation=round(excess * 100, 1),
                        created_at=ts,
                    )
                )

        # ------------------------------------------ rule 3: household load budget
        if total > cfg.household_budget_watts and (
            ts - household_last.get(AlertRule.HOUSEHOLD_BUDGET.value, start - cooldown) > cooldown
        ):
            household_last[AlertRule.HOUSEHOLD_BUDGET.value] = ts
            excess = (total - cfg.household_budget_watts) / cfg.household_budget_watts
            score = score_from_excess(excess)
            alerts.append(
                UsageAlert(
                    device_id=None,
                    rule=AlertRule.HOUSEHOLD_BUDGET.value,
                    severity=severity_for(score).value,
                    score=score,
                    message=(
                        f"Household load {total:,.0f} W exceeded the "
                        f"{cfg.household_budget_watts:,.0f} W budget by {excess * 100:.0f}%."
                    ),
                    value=round(total, 2),
                    baseline=cfg.household_budget_watts,
                    threshold=cfg.household_budget_watts,
                    deviation=round(excess * 100, 1),
                    created_at=ts,
                )
            )

        # -------------------------------------------- rule 4: projected daily use
        kwh_today_total = sum(energy_today.values())
        hours_elapsed = (ts - start_of_day(ts)).total_seconds() / 3600.0
        projected = kwh_today_total / max(0.25, hours_elapsed) * 24.0
        if hours_elapsed >= 6 and projected > cfg.daily_budget_kwh and (
            ts - household_last.get(AlertRule.DAILY_ENERGY.value, start - cooldown) > cooldown
        ):
            household_last[AlertRule.DAILY_ENERGY.value] = ts
            excess = (projected - cfg.daily_budget_kwh) / cfg.daily_budget_kwh
            score = score_from_excess(excess)
            alerts.append(
                UsageAlert(
                    device_id=None,
                    rule=AlertRule.DAILY_ENERGY.value,
                    severity=severity_for(score).value,
                    score=score,
                    message=(
                        f"Projected daily consumption {projected:.1f} kWh is above the "
                        f"{cfg.daily_budget_kwh:.1f} kWh budget."
                    ),
                    value=round(projected, 3),
                    baseline=cfg.daily_budget_kwh,
                    threshold=cfg.daily_budget_kwh,
                    deviation=round(excess * 100, 1),
                    created_at=ts,
                )
            )

    for i in range(0, len(alerts), 500):
        session.add_all(alerts[i : i + 500])
        await session.flush()
    await session.commit()
    log.info("history detection produced %d alerts", len(alerts))
    return len(alerts)
