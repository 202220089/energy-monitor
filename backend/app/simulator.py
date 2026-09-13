"""Smart-plug simulator.

Replaces the "firewall log" source of the original brief with a realistic
appliance model: each device is a two-state Markov-ish machine (ON / standby)
whose duty-cycle, cycle length and jitter are stored on the ``devices`` row.
The same ``step()`` function is used for live ticks *and* for back-filling
history, so the seeded past looks exactly like the live stream.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import datetime

from app.models import Device


@dataclass
class _DeviceRuntime:
    phase: float
    spike_left: int = 0
    spike_factor: float = 1.0


class DeviceSimulator:
    """Generates the next reading for a device given the elapsed seconds."""

    def __init__(self, seed: int = 2024) -> None:
        self._rng = random.Random(seed)
        self._runtime: dict[int, _DeviceRuntime] = {}

    # ------------------------------------------------------------------ public
    def reset(self) -> None:
        self._runtime.clear()

    def step(self, device: Device, now: datetime, dt_seconds: float) -> tuple[float, bool]:
        """Return ``(watts, is_on)`` for the next sample of ``device``."""
        runtime = self._runtime.get(device.id)
        if runtime is None:
            runtime = _DeviceRuntime(phase=self._rng.uniform(0, math.tau))
            self._runtime[device.id] = runtime

        dt = max(0.1, dt_seconds)
        is_on = bool(device.is_on)

        # ---- state transitions (duty cycle over an average on/off cycle) -----
        cycle_s = max(60.0, device.cycle_minutes * 60.0)
        on_s = max(1.0, cycle_s * max(0.0, min(1.0, device.duty_cycle)))
        off_s = max(1.0, cycle_s * (1.0 - max(0.0, min(1.0, device.duty_cycle))))

        if is_on:
            if device.duty_cycle < 0.999 and self._rng.random() < dt / on_s:
                is_on = False
        else:
            if device.duty_cycle > 0.001 and self._rng.random() < dt / off_s:
                is_on = True

        if not is_on:
            watts = max(0.0, device.standby_watts * (1 + self._rng.gauss(0, 0.12)))
            return round(watts, 2), False

        # ---------------------------------------------------------- ON profile
        slow_wave = 0.5 + 0.5 * math.sin(
            now.timestamp() / max(30.0, cycle_s * 1.7) + runtime.phase
        )
        base = device.nominal_watts * (0.72 + 0.34 * slow_wave)
        noise = self._rng.gauss(0.0, device.nominal_watts * max(0.01, device.jitter_pct) * 0.4)
        watts = base + noise

        # occasional fault-like spike: ``spike_probability`` = spikes per hour
        rate_per_hour = max(0.0, device.spike_probability)
        if runtime.spike_left <= 0 and self._rng.random() < rate_per_hour * dt / 3600.0:
            runtime.spike_factor = self._rng.uniform(1.8, 3.2)
            runtime.spike_left = self._rng.randint(1, 4)
        if runtime.spike_left > 0:
            watts *= runtime.spike_factor
            runtime.spike_left -= 1

        watts = max(device.nominal_watts * 0.35, min(watts, device.nominal_watts * 4.0))
        return round(watts, 2), True

    # ------------------------------------------------------------------ utils
    def runtime_state(self, device_id: int) -> dict[str, float]:
        rt = self._runtime.get(device_id)
        if not rt:
            return {}
        return {"phase": rt.phase, "spike_left": rt.spike_left, "spike_factor": rt.spike_factor}


simulator = DeviceSimulator()
