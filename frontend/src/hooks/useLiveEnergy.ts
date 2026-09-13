import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { DeviceLive, HouseholdStats, LiveMessage, UsageAlert } from "../types";

export interface Toast {
  id: number;
  alert: UsageAlert;
}

export interface LiveState {
  connected: boolean;
  paused: boolean;
  household: HouseholdStats | null;
  devices: DeviceLive[];
  alerts: UsageAlert[]; // open alerts, newest first
  toasts: Toast[];
  liveSeries: { ts: string; watts: number }[];
}

const MAX_SERIES = 600;
const MAX_TOASTS = 4;
let toastId = 1;

export function useLiveEnergy() {
  const [connected, setConnected] = useState(false);
  const [paused, setPaused] = useState(false);
  const [household, setHousehold] = useState<HouseholdStats | null>(null);
  const [devices, setDevices] = useState<DeviceLive[]>([]);
  const [alerts, setAlerts] = useState<UsageAlert[]>([]);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [liveSeries, setLiveSeries] = useState<{ ts: string; watts: number }[]>([]);

  const wsRef = useRef<WebSocket | null>(null);
  const retryRef = useRef<number>(0);
  const timerRef = useRef<number | undefined>(undefined);

  const pushToast = useCallback((alert: UsageAlert) => {
    setToasts((prev) => [{ id: toastId++, alert }, ...prev].slice(0, MAX_TOASTS));
    window.setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.alert.id !== alert.id));
    }, 6000);
  }, []);

  useEffect(() => {
    let disposed = false;

    const connect = () => {
      const proto = window.location.protocol === "https:" ? "wss" : "ws";
      const ws = new WebSocket(`${proto}://${window.location.host}/api/ws/live`);
      wsRef.current = ws;

      ws.onopen = () => {
        if (disposed) return;
        setConnected(true);
        retryRef.current = 0;
      };

      ws.onmessage = (event) => {
        if (disposed) return;
        try {
          const message = JSON.parse(event.data) as LiveMessage;
          if (message.type === "snapshot") {
            setHousehold(message.household);
            setDevices(message.devices);
            setAlerts(
              message.recent_alerts
                .filter((a) => !a.acknowledged)
                .sort((a, b) => (a.created_at < b.created_at ? 1 : -1)),
            );
          } else if (message.type === "tick") {
            setHousehold(message.household);
            setDevices(message.devices);
            setLiveSeries((prev) =>
              [...prev, { ts: message.ts, watts: message.household.total_watts }].slice(
                -MAX_SERIES,
              ),
            );
            if (message.alerts.length > 0) {
              setAlerts((prev) => {
                const known = new Set(prev.map((a) => a.id));
                const fresh = message.alerts.filter((a) => !known.has(a.id));
                fresh.forEach(pushToast);
                return [...fresh, ...prev].slice(0, 200);
              });
            }
          }
        } catch {
          /* ignore malformed frames */
        }
      };

      ws.onclose = () => {
        if (disposed) return;
        setConnected(false);
        const delay = Math.min(8000, 1000 * 2 ** retryRef.current++);
        timerRef.current = window.setTimeout(connect, delay);
      };
      ws.onerror = () => ws.close();
    };

    connect();
    return () => {
      disposed = true;
      window.clearTimeout(timerRef.current);
      wsRef.current?.close();
    };
  }, [pushToast]);

  const refreshAlerts = useCallback(() => {
    api
      .alerts("?limit=200")
      .then((list) => setAlerts(list.filter((a) => !a.acknowledged)))
      .catch(() => undefined);
  }, []);

  const ack = useCallback(
    (id: number) => {
      setAlerts((prev) => prev.filter((a) => a.id !== id));
      api.ackAlert(id).catch(refreshAlerts);
    },
    [refreshAlerts],
  );

  const ackAll = useCallback(() => {
    setAlerts([]);
    api.ackAll().catch(refreshAlerts);
  }, [refreshAlerts]);

  const setPausedState = useCallback((value: boolean) => setPaused(value), []);

  return {
    connected,
    paused,
    setPausedState,
    household,
    devices,
    alerts,
    toasts,
    liveSeries,
    ack,
    ackAll,
    refreshAlerts,
  };
}
