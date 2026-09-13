import { useEffect, useState } from "react";
import { api } from "../api";
import { fmt, RULE_LABELS } from "../format";
import type { UsageAlert } from "../types";

interface Props {
  alerts: UsageAlert[];
  onAck: (id: number) => void;
  onAckAll: () => void;
}

interface Stats {
  by_severity: Record<string, number>;
  by_rule: Record<string, number>;
  total: number;
  open: number;
}

export default function AlertsPanel({ alerts, onAck, onAckAll }: Props) {
  const [stats, setStats] = useState<Stats | null>(null);
  const [filter, setFilter] = useState<string>("");

  useEffect(() => {
    let cancelled = false;
    const load = () =>
      api
        .alertStats(24)
        .then((s) => !cancelled && setStats(s))
        .catch(() => undefined);
    load();
    const id = window.setInterval(load, 15000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  const visible = filter ? alerts.filter((a) => a.rule === filter) : alerts;

  return (
    <div className="card">
      <div className="card-head">
        <h2>Usage alerts</h2>
        <span className="hint">{alerts.length} open</span>
        <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
          <select
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            style={{
              border: "1px solid var(--line)",
              borderRadius: 8,
              background: "var(--cream-2)",
              color: "var(--ink)",
              fontSize: 12,
              padding: "4px 8px",
            }}
          >
            <option value="">all rules</option>
            {Object.entries(RULE_LABELS).map(([key, label]) => (
              <option key={key} value={key}>
                {label}
              </option>
            ))}
          </select>
          <button className="btn small" onClick={onAckAll} disabled={!alerts.length}>
            Ack all
          </button>
        </div>
      </div>

      {stats && (
        <div
          style={{
            display: "flex",
            gap: 6,
            padding: "10px 18px 0",
            flexWrap: "wrap",
          }}
        >
          {(["low", "medium", "high", "critical"] as const).map((sev) => (
            <span key={sev} className={`sev ${sev}`} style={{ padding: "4px 10px" }}>
              {sev} {stats.by_severity[sev] ?? 0}
            </span>
          ))}
          <span className="chip z" style={{ marginLeft: "auto" }}>last 24 h: {stats.total}</span>
        </div>
      )}

      <div className="card-body">
        {visible.length === 0 ? (
          <div className="empty">
            All quiet — no open alerts.
            <br />
            Anomalies show up here the moment a rule fires.
          </div>
        ) : (
          <div className="alert-list">
            {visible.slice(0, 60).map((alert) => (
              <div key={alert.id} className={`alert severity-${alert.severity}`}>
                <div className="row1">
                  <span className="rule">{RULE_LABELS[alert.rule] ?? alert.rule}</span>
                  {alert.device_name && (
                    <span style={{ fontSize: 11.5, color: "var(--brown-soft)", fontWeight: 700 }}>
                      {alert.device_name}
                    </span>
                  )}
                  <span className={`sev ${alert.severity}`}>{alert.severity}</span>
                </div>
                <div className="msg">{alert.message}</div>
                <div className="row3">
                  <span>score {alert.score.toFixed(0)}/100</span>
                  <div className="score-bar">
                    <div style={{ width: `${alert.score}%` }} />
                  </div>
                  <span>{fmt.time(alert.created_at)}</span>
                  <button className="btn small ghost" onClick={() => onAck(alert.id)}>
                    Ack
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
