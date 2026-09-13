import type { AppSettings, SeriesPoint, UsageAlert } from "./types";

const BASE = "/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status} ${body}`);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  overview: () => request<any>("/stats/overview"),
  series: (deviceId: number | null, window = "6h", points = 180) =>
    request<{ bucket_seconds: number; points: SeriesPoint[] }>(
      `/readings/series?window=${window}&points=${points}${
        deviceId !== null ? `&device_id=${deviceId}` : ""
      }`,
    ),
  alerts: (params: string = "") => request<UsageAlert[]>(`/alerts${params}`),
  alertStats: (hours = 24) => request<any>(`/alerts/stats?since_hours=${hours}`),
  ackAlert: (id: number, acknowledged = true) =>
    request<UsageAlert>(`/alerts/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ acknowledged }),
    }),
  ackAll: () => request<{ acknowledged: number }>("/alerts/ack-all", { method: "POST" }),
  settings: () => request<AppSettings>("/settings"),
  updateSettings: (patch: Partial<AppSettings>) =>
    request<AppSettings>("/settings", { method: "PATCH", body: JSON.stringify(patch) }),
  simulator: (action: "start" | "stop") =>
    request<any>(`/simulator/${action}`, { method: "POST" }),
};
