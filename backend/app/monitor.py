"""The live pipeline: simulator -> readings -> detection -> WebSocket broadcast.

One asyncio task drives the whole thing:

    tick()
      ├─ generate one reading per active smart plug   (app.simulator)
      ├─ persist them                                 (readings table)
      ├─ run the three detection rules                (app.detection)
      ├─ persist the alerts they raise                (usage_alerts table)
      └─ broadcast a compact JSON payload             (app.ws)
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import SessionLocal
from app.deps import elapsed_hours, get_app_settings, utcnow
from app.detection import AlertEngine, Sample
from app.models import AppSettings, Device, Reading
from app.schemas import AlertOut, DeviceLive, HouseholdStats, TickMessage
from app.simulator import simulator
from app.stats_service import device_stats, household_stats
from app.ws import manager

log = logging.getLogger("energy.monitor")

settings = get_settings()


class EnergyMonitor:
    """Background tick loop + the state needed to build the live payload."""

    def __init__(self) -> None:
        self.engine = AlertEngine()
        self.running = False
        self.ticks = 0
        self.last_tick_at: datetime | None = None
        self._task: asyncio.Task | None = None
        self._stopping = asyncio.Event()

    # ------------------------------------------------------------------ control
    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self.running = True
        self._stopping.clear()
        self._task = asyncio.create_task(self._loop(), name="energy-monitor")
        log.info("energy monitor started")

    async def stop(self) -> None:
        self.running = False
        self._stopping.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        log.info("energy monitor stopped")

    async def _loop(self) -> None:
        while True:
            cfg = await self._read_settings()
            if cfg is None:
                await asyncio.sleep(1)
                continue
            if cfg.simulator_running:
                try:
                    await self.tick()
                except asyncio.CancelledError:
                    raise
                except Exception:  # keep the stream alive on transient errors
                    log.exception("tick failed")
            try:
                await asyncio.wait_for(
                    self._stopping.wait(), timeout=max(0.5, cfg.tick_seconds)
                )
            except asyncio.TimeoutError:
                pass

    async def _read_settings(self) -> AppSettings | None:
        try:
            async with SessionLocal() as session:
                return await get_app_settings(session)
        except Exception:
            log.exception("cannot read settings")
            return None

    # -------------------------------------------------------------------- tick
    async def tick(self) -> None:
        async with SessionLocal() as session:
            cfg = await get_app_settings(session)
            now = utcnow()
            dt = max(0.5, float(cfg.tick_seconds))

            devices = list(
                (
                    await session.execute(
                        select(Device).where(Device.active.is_(True)).order_by(Device.id)
                    )
                )
                .scalars()
                .all()
            )
            if not devices:
                return

            readings: list[Reading] = []
            samples: list[Sample] = []
            for device in devices:
                watts, is_on = simulator.step(device, now, dt)
                device.is_on = is_on
                device.last_watts = watts
                device.last_reading_at = now
                readings.append(
                    Reading(device_id=device.id, watts=watts, is_on=is_on, ts=now)
                )
                samples.append(
                    Sample(
                        device_id=device.id,
                        device_name=device.name,
                        watts=watts,
                        is_on=is_on,
                    )
                )

            session.add_all(readings)
            await session.flush()

            stats = await device_stats(session, [d.id for d in devices], cfg, now)
            kwh_today = sum(s.kwh_today for s in stats.values())
            projected = kwh_today / elapsed_hours(now) * 24.0

            alerts = await self.engine.evaluate(
                session,
                cfg,
                now,
                samples,
                {d.id: d.created_at for d in devices},
                kwh_today,
                projected,
            )
            for alert in alerts:
                session.add(alert)
            await session.commit()

            household = await household_stats(session, cfg, now, devices, stats)
            live = self._build_live(devices, stats, cfg, now, alerts)
            alert_payload = [
                AlertOut.model_validate(
                    alert,
                    from_attributes=True,
                ).model_copy(
                    update={
                        "device_name": next(
                            (d.name for d in devices if d.id == alert.device_id), None
                        )
                    }
                )
                for alert in alerts
            ]

            self.ticks += 1
            self.last_tick_at = now

        message = TickMessage(
            ts=now,
            household=HouseholdStats(**household),
            devices=live,
            alerts=alert_payload,
        ).model_dump(mode="json")
        await manager.broadcast(message)

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _build_live(
        devices: list[Device],
        stats: dict[int, "DeviceStat"],  # type: ignore[valid-type]  # noqa: F821
        cfg: AppSettings,
        now: datetime,
        alerts: list,
    ) -> list[DeviceLive]:
        alerted = {a.device_id for a in alerts if a.device_id is not None}
        out: list[DeviceLive] = []
        for device in devices:
            stat = stats.get(device.id)
            avg = stat.avg_watts if stat else None
            std = stat.std_watts if stat else None
            z: float | None = None
            deviation_pct: float | None = None
            if avg and std is not None and device.is_on:
                std_eff = max(std, avg * 0.05, 1.0)
                z = round((device.last_watts - avg) / std_eff, 2)
                deviation_pct = round((device.last_watts - avg) / avg * 100.0, 1)

            if device.id in alerted:
                status = "alert"
            elif (
                (z is not None and z >= max(1.5, cfg.z_threshold - 1))
                or (stat and stat.on_minutes >= cfg.max_on_minutes * 0.75)
            ):
                status = "watch"
            else:
                status = "normal"

            out.append(
                DeviceLive(
                    id=device.id,
                    name=device.name,
                    category=device.category,
                    room=device.room,
                    watts=round(device.last_watts, 1),
                    is_on=device.is_on,
                    active=device.active,
                    nominal_watts=device.nominal_watts,
                    standby_watts=device.standby_watts,
                    avg_watts=avg,
                    z_score=z,
                    deviation_pct=deviation_pct,
                    on_minutes=stat.on_minutes if stat else 0.0,
                    kwh_today=stat.kwh_today if stat else 0.0,
                    status=status,  # type: ignore[arg-type]
                    ts=now,
                )
            )
        return out


monitor = EnergyMonitor()
