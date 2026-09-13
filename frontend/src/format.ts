export const fmt = {
  watts: (v: number) =>
    v >= 1000 ? `${(v / 1000).toFixed(2)} kW` : `${Math.round(v)} W`,
  number: (v: number, digits = 1) =>
    v.toLocaleString("en-US", { maximumFractionDigits: digits, minimumFractionDigits: 0 }),
  kwh: (v: number) => `${v.toFixed(1)} kWh`,
  money: (v: number, currency: string) =>
    `${v.toFixed(2)} ${currency}`,
  time: (iso: string) =>
    new Date(iso).toLocaleTimeString("en-US", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    }),
  shortTime: (iso: string) =>
    new Date(iso).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false }),
  minutes: (m: number) =>
    m >= 60 ? `${Math.floor(m / 60)}h ${Math.round(m % 60)}m` : `${Math.round(m)}m`,
};

export const RULE_LABELS: Record<string, string> = {
  spike: "Power spike",
  on_too_long: "Running too long",
  household_budget: "Load budget",
  daily_energy: "Daily budget",
};
