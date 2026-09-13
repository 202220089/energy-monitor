import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import AlertsPanel from "./components/AlertsPanel";
import DeviceGrid from "./components/DeviceGrid";
import Header from "./components/Header";
import KpiCards from "./components/KpiCards";
import PowerChart from "./components/PowerChart";
import SettingsPanel from "./components/SettingsPanel";
import Toasts from "./components/Toasts";
import { useLiveEnergy } from "./hooks/useLiveEnergy";

export default function App() {
  const live = useLiveEnergy();
  const [simRunning, setSimRunning] = useState(true);

  const refreshSim = useCallback(() => {
    api
      .settings()
      .then((s) => setSimRunning(s.simulator_running))
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    api
      .settings()
      .then((s) => setSimRunning(s.simulator_running))
      .catch(() => undefined);
  }, []);

  const toggleSim = useCallback(async () => {
    try {
      const status = await api.simulator(simRunning ? "stop" : "start");
      setSimRunning(status.running);
      live.setPausedState(!status.running);
    } catch {
      /* backend unreachable */
    }
  }, [simRunning, live]);

  return (
    <>
      <Header connected={live.connected} paused={!simRunning} onToggleSim={toggleSim} />

      <div className="page">
        <KpiCards household={live.household} />

        <div className="main-grid">
          <div className="left-col">
            <PowerChart household={live.household} liveSeries={live.liveSeries} />
            <DeviceGrid devices={live.devices} />
          </div>

          <div className="right-col">
            <AlertsPanel alerts={live.alerts} onAck={live.ack} onAckAll={live.ackAll} />
            <SettingsPanel onChanged={refreshSim} />
          </div>
        </div>

        <p className="footer-note">
         
        </p>
      </div>

      <Toasts toasts={live.toasts} />
    </>
  );
}
