import { useEffect, useState } from "react";

interface Props {
  connected: boolean;
  paused: boolean;
  onToggleSim: () => void;
}

export default function Header({ connected, paused, onToggleSim }: Props) {
  const [now, setNow] = useState(new Date());

  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(id);
  }, []);

  const live = connected && !paused;

  return (
    <header className="topbar">
      <div className="brand">
        <svg width="42" height="42" viewBox="0 0 64 64" aria-hidden="true">
          <rect width="64" height="64" rx="14" fill="#E7B93C" />
          <rect x="3" y="3" width="58" height="58" rx="12" fill="none" stroke="#2E1C11" strokeWidth="2" opacity="0.35" />
          <path d="M36 8 L18 36 h11 L26 56 L46 26 H34 Z" fill="#2E1C11" />
        </svg>
        <div>
          <h1>HomeWatt</h1>
          <p className="tagline">Smart Home Energy Monitor</p>
        </div>
      </div>

      <div className="spacer" />

      <span className="clock">
        {now.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" })}{" "}
        ·{" "}
        {now.toLocaleTimeString("en-US", { hour12: false })}
      </span>

      <span className={`live-pill ${live ? "" : "paused"}`}>
        <span className="live-dot" />
        {!connected ? "RECONNECTING…" : paused ? "STREAM PAUSED" : "LIVE"}
      </span>

      <button className="btn ghost" style={{ color: "#f0e2c0", borderColor: "#7a5c43" }} onClick={onToggleSim}>
        {paused ? "Resume stream" : "Pause stream"}
      </button>
    </header>
  );
}
