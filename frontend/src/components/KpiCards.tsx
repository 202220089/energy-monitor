import type { HouseholdStats } from "../types";
import { fmt } from "../format";

export default function KpiCards({ household }: { household: HouseholdStats | null }) {
  if (!household) {
    return (
      <div className="kpi-row">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="kpi">
            <div className="label">loading…</div>
            <div className="value">—</div>
          </div>
        ))}
      </div>
    );
  }

  const loadPct = Math.min(100, household.budget_used_pct);
  const energyPct = Math.min(100, (household.kwh_today / household.kwh_budget) * 100);
  const projectedPct = Math.min(100, (household.projected_kwh_today / household.kwh_budget) * 100);

  return (
    <div className="kpi-row">
      <div className="kpi">
        <div className="label">Current load</div>
        <div className="value">
          {fmt.number(household.total_watts, 0)}
          <small>W</small>
        </div>
        <div className="sub">
          {household.budget_used_pct.toFixed(0)}% of the {fmt.number(household.budget_watts, 0)} W budget ·{" "}
          {household.devices_on}/{household.devices_total} devices on
        </div>
        <div className="meter">
          <div className={household.budget_used_pct > 100 ? "over" : ""} style={{ width: `${loadPct}%` }} />
        </div>
      </div>

      <div className="kpi">
        <div className="label">Energy today</div>
        <div className="value">
          {household.kwh_today.toFixed(1)}
          <small>kWh</small>
        </div>
        <div className="sub">
          projected {household.projected_kwh_today.toFixed(1)} kWh of {household.kwh_budget.toFixed(0)} kWh budget
        </div>
        <div className="meter">
          <div
            className={projectedPct > 100 ? "over" : ""}
            style={{ width: `${Math.max(energyPct, projectedPct * 0)}%` }}
          />
        </div>
      </div>

      <div className="kpi">
        <div className="label">Cost today</div>
        <div className="value">
          {fmt.money(household.cost_today, household.currency)}
        </div>
        <div className="sub">
          at {household.price_per_kwh.toFixed(2)} {household.currency}/kWh · devices online {household.devices_online}
        </div>
      </div>

      <div className="kpi">
        <div className="label">Open alerts</div>
        <div className="value" style={{ color: household.critical_alerts > 0 ? "var(--critical)" : undefined }}>
          {household.open_alerts}
        </div>
        <div className="sub">{household.critical_alerts} high / critical</div>
      </div>
    </div>
  );
}
