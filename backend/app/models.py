"""SQLAlchemy ORM models: devices, readings, usage_alerts, settings.

Mirrors the project brief:
  * `readings`      -> one row per smart-plug sample (device, watts, timestamp)
  * `usage_alerts`  -> one row per detected anomaly (rule, score, severity)
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy import Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class AlertRule(str, enum.Enum):
    SPIKE = "spike"                       # device draws way more power than normal
    ON_TOO_LONG = "on_too_long"           # device has been running unusually long
    HOUSEHOLD_BUDGET = "household_budget"  # total household load above the budget
    DAILY_ENERGY = "daily_energy"          # projected daily energy above the budget


class AlertSeverity(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Device(Base):
    """A simulated smart plug / appliance."""

    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(40), nullable=False, default="appliance")
    room: Mapped[str] = mapped_column(String(60), nullable=False, default="Living Room")

    # simulation profile
    nominal_watts: Mapped[float] = mapped_column(Float, nullable=False, default=150.0)
    standby_watts: Mapped[float] = mapped_column(Float, nullable=False, default=3.0)
    duty_cycle: Mapped[float] = mapped_column(Float, nullable=False, default=0.35)
    cycle_minutes: Mapped[float] = mapped_column(Float, nullable=False, default=30.0)
    spike_probability: Mapped[float] = mapped_column(Float, nullable=False, default=0.01)
    jitter_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.08)

    # live state (cached, so the dashboard renders instantly)
    is_on: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_watts: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    last_reading_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    readings: Mapped[list["Reading"]] = relationship(
        back_populates="device", cascade="all, delete-orphan", passive_deletes=True
    )
    alerts: Mapped[list["UsageAlert"]] = relationship(
        back_populates="device", cascade="all, delete-orphan", passive_deletes=True
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<Device {self.name!r} {self.last_watts:.0f}W>"


class Reading(Base):
    """One power sample emitted by a smart plug."""

    __tablename__ = "readings"
    __table_args__ = (Index("ix_readings_device_ts", "device_id", "ts"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[int] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    watts: Mapped[float] = mapped_column(Float, nullable=False)
    is_on: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    device: Mapped["Device"] = relationship(back_populates="readings")


class UsageAlert(Base):
    """A detected anomaly, scored by how far it drifts from 'normal'."""

    __tablename__ = "usage_alerts"
    __table_args__ = (
        Index("ix_alerts_created_at", "created_at"),
        Index("ix_alerts_device_rule", "device_id", "rule"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[int | None] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), index=True
    )
    rule: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default=AlertSeverity.LOW.value)
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)  # 0-100
    message: Mapped[str] = mapped_column(Text, nullable=False)

    value: Mapped[float | None] = mapped_column(Float)          # observed value
    baseline: Mapped[float | None] = mapped_column(Float)       # rolling average / expected
    threshold: Mapped[float | None] = mapped_column(Float)      # trigger level
    deviation: Mapped[float | None] = mapped_column(Float)      # z-score or % above threshold

    acknowledged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    device: Mapped["Device | None"] = relationship(back_populates="alerts")


class AppSettings(Base):
    """Single-row table (id = 1) holding tunable detection thresholds."""

    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    household_budget_watts: Mapped[float] = mapped_column(Float, nullable=False, default=4000.0)
    daily_budget_kwh: Mapped[float] = mapped_column(Float, nullable=False, default=70.0)
    z_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=3.0)
    baseline_window_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    min_baseline_samples: Mapped[int] = mapped_column(Integer, nullable=False, default=12)
    max_on_minutes: Mapped[float] = mapped_column(Float, nullable=False, default=120.0)
    alert_cooldown_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=90)
    tick_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=2.0)
    simulator_running: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    price_per_kwh: Mapped[float] = mapped_column(Float, nullable=False, default=0.12)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
