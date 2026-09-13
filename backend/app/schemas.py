"""Pydantic v2 request/response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models import AlertRule, AlertSeverity

# --------------------------------------------------------------------- devices


class DeviceBase(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    category: str = Field(default="appliance", max_length=40)
    room: str = Field(default="Living Room", max_length=60)
    nominal_watts: float = Field(default=150.0, gt=0)
    standby_watts: float = Field(default=3.0, ge=0)
    duty_cycle: float = Field(default=0.35, ge=0, le=1)
    cycle_minutes: float = Field(default=30.0, gt=0)
    spike_probability: float = Field(default=0.01, ge=0, le=1)
    jitter_pct: float = Field(default=0.08, ge=0, le=1)
    active: bool = True


class DeviceCreate(DeviceBase):
    pass


class DeviceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    category: str | None = None
    room: str | None = None
    nominal_watts: float | None = Field(default=None, gt=0)
    standby_watts: float | None = Field(default=None, ge=0)
    duty_cycle: float | None = Field(default=None, ge=0, le=1)
    cycle_minutes: float | None = Field(default=None, gt=0)
    spike_probability: float | None = Field(default=None, ge=0, le=1)
    jitter_pct: float | None = Field(default=None, ge=0, le=1)
    active: bool | None = None


class DeviceOut(DeviceBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    is_on: bool
    last_watts: float
    last_reading_at: datetime | None
    created_at: datetime


class DeviceLive(BaseModel):
    """Per-device payload pushed through the WebSocket on every tick."""

    id: int
    name: str
    category: str
    room: str
    watts: float
    is_on: bool
    active: bool
    nominal_watts: float
    standby_watts: float
    avg_watts: float | None = None       # rolling baseline (ON samples)
    z_score: float | None = None         # how far from normal, in std-devs
    deviation_pct: float | None = None   # (watts - avg) / avg * 100
    on_minutes: float = 0.0              # length of the current ON streak
    kwh_today: float = 0.0
    status: Literal["normal", "watch", "alert"] = "normal"
    ts: datetime


# -------------------------------------------------------------------- readings


class ReadingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    device_id: int
    watts: float
    is_on: bool
    ts: datetime


class SeriesPoint(BaseModel):
    ts: datetime
    watts: float


class SeriesOut(BaseModel):
    device_id: int | None = None
    device_name: str | None = None
    bucket_seconds: int
    points: list[SeriesPoint]


# ---------------------------------------------------------------------- alerts


class AlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    device_id: int | None
    device_name: str | None = None
    rule: str
    severity: str
    score: float
    message: str
    value: float | None = None
    baseline: float | None = None
    threshold: float | None = None
    deviation: float | None = None
    acknowledged: bool
    acknowledged_at: datetime | None = None
    created_at: datetime


class AlertAck(BaseModel):
    acknowledged: bool = True


# -------------------------------------------------------------------- settings


class SettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    household_budget_watts: float
    daily_budget_kwh: float
    z_threshold: float
    baseline_window_minutes: int
    min_baseline_samples: int
    max_on_minutes: float
    alert_cooldown_seconds: int
    tick_seconds: float
    simulator_running: bool
    price_per_kwh: float
    currency: str
    updated_at: datetime


class SettingsUpdate(BaseModel):
    household_budget_watts: float | None = Field(default=None, gt=0)
    daily_budget_kwh: float | None = Field(default=None, gt=0)
    z_threshold: float | None = Field(default=None, gt=0)
    baseline_window_minutes: int | None = Field(default=None, ge=5, le=1440)
    min_baseline_samples: int | None = Field(default=None, ge=3, le=1000)
    max_on_minutes: float | None = Field(default=None, gt=0)
    alert_cooldown_seconds: int | None = Field(default=None, ge=0, le=3600)
    tick_seconds: float | None = Field(default=None, ge=0.5, le=60)
    simulator_running: bool | None = None
    price_per_kwh: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, max_length=8)


# ------------------------------------------------------------------ dashboard


class HouseholdStats(BaseModel):
    total_watts: float
    budget_watts: float
    budget_used_pct: float
    devices_online: int
    devices_on: int
    devices_total: int
    kwh_today: float
    kwh_budget: float
    projected_kwh_today: float
    cost_today: float
    price_per_kwh: float
    currency: str
    open_alerts: int
    critical_alerts: int
    ts: datetime


class DeviceEnergy(BaseModel):
    device_id: int
    device_name: str
    room: str
    kwh: float
    share_pct: float


class LiveSnapshot(BaseModel):
    """Initial payload sent to a freshly connected WebSocket client."""

    type: str = "snapshot"
    ts: datetime
    household: HouseholdStats
    devices: list[DeviceLive]
    recent_alerts: list[AlertOut]


class TickMessage(BaseModel):
    """Payload broadcast on every simulator tick."""

    type: str = "tick"
    ts: datetime
    household: HouseholdStats
    devices: list[DeviceLive]
    alerts: list[AlertOut] = []


class SimulatorStatus(BaseModel):
    running: bool
    tick_seconds: float
    devices: int
    ticks: int


AlertRuleLiteral = Literal[
    AlertRule.SPIKE.value,
    AlertRule.ON_TOO_LONG.value,
    AlertRule.HOUSEHOLD_BUDGET.value,
    AlertRule.DAILY_ENERGY.value,
]

SeverityLiteral = Literal[
    AlertSeverity.LOW.value,
    AlertSeverity.MEDIUM.value,
    AlertSeverity.HIGH.value,
    AlertSeverity.CRITICAL.value,
]
