import { useEffect, useState } from "react";
import { api } from "../api";
import type { AppSettings } from "../types";

interface Props {
  onChanged: () => void;
}

const FIELDS: { key: keyof AppSettings; label: string; step?: string }[] = [
  { key: "household_budget_watts", label: "Load budget (W)" },
  { key: "daily_budget_kwh", label: "Daily budget (kWh)" },
  { key: "z_threshold", label: "Spike z-score", step: "0.5" },
  { key: "max_on_minutes", label: "Max run time (min)" },
  { key: "baseline_window_minutes", label: "Baseline window (min)" },
  { key: "alert_cooldown_seconds", label: "Alert cooldown (s)" },
  { key: "price_per_kwh", label: "Price / kWh", step: "0.01" },
  { key: "tick_seconds", label: "Tick (s)", step: "0.5" },
];

export default function SettingsPanel({ onChanged }: Props) {
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .settings()
      .then((s) => {
        setSettings(s);
        setDraft(Object.fromEntries(FIELDS.map((f) => [f.key, String(s[f.key])])));
      })
      .catch((e) => setError(String(e)));
  }, []);

  const save = async () => {
    if (!settings) return;
    const patch: Record<string, number> = {};
    for (const f of FIELDS) {
      const value = Number(draft[f.key]);
      if (!Number.isNaN(value) && value !== settings[f.key]) patch[f.key as string] = value;
    }
    try {
      const updated = await api.updateSettings(patch);
      setSettings(updated);
      setDraft(Object.fromEntries(FIELDS.map((f) => [f.key, String(updated[f.key])])));
      setSaved(true);
      setError("");
      window.setTimeout(() => setSaved(false), 1800);
      onChanged();
    } catch (e) {
      setError(String(e));
    }
  };

  return (
    <div className="card">
      <div className="card-head">
        <h2>Detection & budgets</h2>
        <span className="hint">live thresholds used by the rules engine</span>
      </div>
      <div className="card-body">
        <div className="settings-grid">
          {FIELDS.map((f) => (
            <div className="field" key={f.key as string}>
              <label>{f.label}</label>
              <input
                type="number"
                step={f.step ?? "1"}
                value={draft[f.key as string] ?? ""}
                onChange={(e) => setDraft((d) => ({ ...d, [f.key as string]: e.target.value }))}
              />
            </div>
          ))}
        </div>
        <div style={{ display: "flex", gap: 10, marginTop: 14, alignItems: "center" }}>
          <button className="btn" onClick={save}>
            Save thresholds
          </button>
          {saved && <span style={{ color: "var(--ok)", fontSize: 12.5, fontWeight: 700 }}>saved ✓</span>}
          {error && <span style={{ color: "var(--critical)", fontSize: 12 }}>{error}</span>}
        </div>
      </div>
    </div>
  );
}
