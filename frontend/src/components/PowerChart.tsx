import { useEffect, useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "../api";
import { fmt } from "../format";
import type { HouseholdStats, SeriesPoint } from "../types";

interface Props {
  household: HouseholdStats | null;
  liveSeries: { ts: string; watts: number }[];
}

export default function PowerChart({ household, liveSeries }: Props) {
  const [seed, setSeed] = useState<SeriesPoint[]>([]);

  useEffect(() => {
    let cancelled = false;
    api
      .series(null, "6h", 180)
      .then((s) => !cancelled && setSeed(s.points))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  const data = useMemo(() => {
    const merged = [
      ...seed.map((p) => ({ t: new Date(p.ts).getTime(), watts: p.watts })),
      ...liveSeries.map((p) => ({ t: new Date(p.ts).getTime(), watts: p.watts })),
    ];
    // keep only the last 6 hours so the axis stays readable
    const horizon = Date.now() - 6 * 3600 * 1000;
    return merged.filter((p) => p.t >= horizon);
  }, [seed, liveSeries]);

  return (
    <div className="card">
      <div className="card-head">
        <h2>Household power draw</h2>
        <span className="hint">
          live · rolling 6 h · budget {household ? fmt.number(household.budget_watts, 0) : "—"} W
        </span>
      </div>
      <div className="card-body" style={{ height: 280 }}>
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 8, right: 12, left: -8, bottom: 0 }}>
            <defs>
              <linearGradient id="goldFill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#E7B93C" stopOpacity={0.75} />
                <stop offset="100%" stopColor="#E7B93C" stopOpacity={0.06} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke="#EDE3C8" strokeDasharray="3 6" vertical={false} />
            <XAxis
              dataKey="t"
              type="number"
              domain={["dataMin", "dataMax"]}
              tickFormatter={(t: number) => fmt.shortTime(new Date(t).toISOString())}
              tick={{ fill: "#8A7457", fontSize: 11 }}
              stroke="#E3D5B2"
              tickCount={7}
            />
            <YAxis
              tick={{ fill: "#8A7457", fontSize: 11 }}
              stroke="#E3D5B2"
              tickFormatter={(v: number) => (v >= 1000 ? `${(v / 1000).toFixed(1)}k` : `${v}`)}
              width={44}
            />
            <Tooltip
              contentStyle={{
                background: "#FFFDF4",
                border: "1px solid #E3D5B2",
                borderRadius: 10,
                color: "#35261A",
                fontSize: 12,
              }}
              labelFormatter={(t) => fmt.time(new Date(Number(t)).toISOString())}
              formatter={(value: any) => [fmt.watts(Number(value)), "Load"]}
            />
            {household && (
              <ReferenceLine
                y={household.budget_watts}
                stroke="#8C2B1B"
                strokeDasharray="6 5"
                label={{
                  value: "budget",
                  position: "insideTopRight",
                  fill: "#8C2B1B",
                  fontSize: 11,
                }}
              />
            )}
            <Area
              type="monotone"
              dataKey="watts"
              stroke="#A87B0F"
              strokeWidth={2}
              fill="url(#goldFill)"
              isAnimationActive={false}
              dot={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
