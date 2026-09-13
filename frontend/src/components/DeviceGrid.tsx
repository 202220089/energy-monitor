import { useEffect, useRef, useState } from "react";
import { Area, AreaChart, ResponsiveContainer, YAxis } from "recharts";
import { api } from "../api";
import { fmt } from "../format";
import type { DeviceLive, SeriesPoint } from "../types";

interface Props {
  devices: DeviceLive[];
}

const MAX_SPARK = 90;

function DeviceCard({ device, history }: { device: DeviceLive; history: SeriesPoint[] }) {
  const hot = device.status === "alert";
  return (
    <div className={`device status-${device.status}`}>
      <div className="head">
        <span className={`state-led ${device.is_on ? "on" : ""}`} />
        <span className="name" title={`${device.name} · ${device.room}`}>
          {device.name}
        </span>
      </div>
      <div className="watts">
        {fmt.number(device.watts, 0)} <small>W</small>
      </div>
      <div className="spark">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={history} margin={{ top: 2, right: 0, left: 0, bottom: 0 }}>
            <YAxis hide domain={[0, Math.max(device.nominal_watts * 2.2, 50)]} />
            <Area
              type="monotone"
              dataKey="watts"
              stroke={hot ? "#B4551D" : "#C9971C"}
              strokeWidth={1.6}
              fill={hot ? "rgba(180,85,29,0.18)" : "rgba(201,151,28,0.16)"}
              isAnimationActive={false}
              dot={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
      <div className="meta">
        <span className="chip">{device.is_on ? "ON" : "standby"}</span>
        {device.avg_watts !== null && (
          <span className={`chip z ${hot ? "hot" : ""}`}>
            μ {fmt.number(device.avg_watts, 0)} W
            {device.z_score !== null ? ` · z ${device.z_score.toFixed(1)}` : ""}
          </span>
        )}
        {device.on_minutes > 0 && <span className="chip z">{fmt.minutes(device.on_minutes)} on</span>}
        <span className="chip z">{device.kwh_today.toFixed(2)} kWh</span>
      </div>
      <div className="meta">
        <span>
          {device.category} · {device.room}
        </span>
      </div>
    </div>
  );
}

export default function DeviceGrid({ devices }: Props) {
  const [seed, setSeed] = useState<Record<number, SeriesPoint[]>>({});
  const liveRef = useRef<Record<number, SeriesPoint[]>>({});
  const [tickHistory, setTickHistory] = useState<Record<number, SeriesPoint[]>>({});

  // seed sparklines once with the recent series of every device
  useEffect(() => {
    let cancelled = false;
    if (!devices.length || Object.keys(seed).length) return;
    Promise.all(
      devices.map((d): Promise<readonly [number, readonly SeriesPoint[]]> =>
        api
          .series(d.id, "2h", 60)
          .then((s) => [d.id, s.points] as const)
          .catch(() => [d.id, [] as SeriesPoint[]] as const),
      ),
    ).then((entries) => {
      if (cancelled) return;
      const map: Record<number, SeriesPoint[]> = {};
      for (const [id, points] of entries) map[id] = [...points];
      setSeed(map);
      liveRef.current = Object.fromEntries(
        Object.entries(map).map(([id, pts]) => [Number(id), [...pts]]),
      );
    });
    return () => {
      cancelled = true;
    };
  }, [devices, seed]);

  // append the live tick of each device
  useEffect(() => {
    if (!devices.length) return;
    const next: Record<number, SeriesPoint[]> = { ...liveRef.current };
    for (const d of devices) {
      const arr = next[d.id] ?? [];
      next[d.id] = [...arr, { ts: d.ts, watts: d.watts }].slice(-MAX_SPARK);
    }
    liveRef.current = next;
    setTickHistory({ ...next });
  }, [devices]);

  return (
    <div className="card">
      <div className="card-head">
        <h2>Smart plugs</h2>
        <span className="hint">
          {devices.filter((d) => d.is_on).length} running · {devices.length} online
        </span>
      </div>
      <div className="card-body">
        <div className="device-grid">
          {devices.map((d) => (
            <DeviceCard key={d.id} device={d} history={tickHistory[d.id] ?? seed[d.id] ?? []} />
          ))}
        </div>
      </div>
    </div>
  );
}
