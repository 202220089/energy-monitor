export interface DeviceLive {
  id: number;
  name: string;
  category: string;
  room: string;
  watts: number;
  is_on: boolean;
  active: boolean;
  nominal_watts: number;
  standby_watts: number;
  avg_watts: number | null;
  z_score: number | null;
  deviation_pct: number | null;
  on_minutes: number;
  kwh_today: number;
  status: "normal" | "watch" | "alert";
  ts: string;
}

export interface HouseholdStats {
  total_watts: number;
  budget_watts: number;
  budget_used_pct: number;
  devices_online: number;
  devices_on: number;
  devices_total: number;
  kwh_today: number;
  kwh_budget: number;
  projected_kwh_today: number;
  cost_today: number;
  price_per_kwh: number;
  currency: string;
  open_alerts: number;
  critical_alerts: number;
  ts: string;
}

export interface UsageAlert {
  id: number;
  device_id: number | null;
  device_name: string | null;
  rule: string;
  severity: "low" | "medium" | "high" | "critical";
  score: number;
  message: string;
  value: number | null;
  baseline: number | null;
  threshold: number | null;
  deviation: number | null;
  acknowledged: boolean;
  acknowledged_at: string | null;
  created_at: string;
}

export interface AppSettings {
  id: number;
  household_budget_watts: number;
  daily_budget_kwh: number;
  z_threshold: number;
  baseline_window_minutes: number;
  min_baseline_samples: number;
  max_on_minutes: number;
  alert_cooldown_seconds: number;
  tick_seconds: number;
  simulator_running: boolean;
  price_per_kwh: number;
  currency: string;
  updated_at: string;
}

export interface SeriesPoint {
  ts: string;
  watts: number;
}

export type LiveMessage =
  | {
      type: "snapshot";
      ts: string;
      household: HouseholdStats;
      devices: DeviceLive[];
      recent_alerts: UsageAlert[];
    }
  | {
      type: "tick";
      ts: string;
      household: HouseholdStats;
      devices: DeviceLive[];
      alerts: UsageAlert[];
    }
  | { type: "pong" };
