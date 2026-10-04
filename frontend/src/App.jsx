import { useState } from "react";
import "./styles/layout.css";
import SideNav from "./components/SideNav";
import TopBar from "./components/TopBar";
import Cockpit from "./pages/Cockpit";
import LiveCluster from "./pages/LiveCluster";
import M4Demo from "./pages/M4Demo";
import TestModels from "./pages/TestModels";
import Explainability from "./pages/Explainability";
import Performance from "./pages/Performance";

const STATUS_LABELS = {
  idle: "En attente",
  running: "Scénario en cours",
  paused: "En pause",
  complete: "Scénario terminé",
  error: "Erreur",
};

const STATUS_TONES = {
  idle: "neutral",
  running: "signal",
  paused: "amber",
  complete: "signal",
  error: "critical",
};

const VALID_VIEWS = ["cockpit", "m4demo", "live", "test", "explainability", "performance"];

// Lit ?view=... dans l'URL au premier rendu, pour permettre un lien direct
// (ex: depuis Grafana) vers une page précise plutôt que de toujours atterrir sur
// la Cockpit par défaut. Aucun routage complet ajouté ici -- juste ce minimum,
// l'app reste par ailleurs un état React en mémoire comme avant.
function initialViewFromUrl() {
  const requested = new URLSearchParams(window.location.search).get("view");
  return VALID_VIEWS.includes(requested) ? requested : "cockpit";
}

export default function App() {
  const [active, setActive] = useState(initialViewFromUrl);
  const [scenarioStatus, setScenarioStatus] = useState("idle");
  const [connected, setConnected] = useState(false);
  const [kiosk, setKiosk] = useState(false);

  const toggleKiosk = () => {
    const next = !kiosk;
    setKiosk(next);
    if (next && document.documentElement.requestFullscreen) {
      document.documentElement.requestFullscreen().catch(() => {});
    } else if (!next && document.fullscreenElement) {
      document.exitFullscreen().catch(() => {});
    }
  };

  return (
    <div className={`shell ${kiosk ? "shell--kiosk" : ""}`}>
      {!kiosk && <SideNav active={active} onChange={setActive} />}
      <div className="shell__main">
        <TopBar
          connected={connected}
          statusLabel={STATUS_LABELS[scenarioStatus]}
          statusTone={STATUS_TONES[scenarioStatus]}
          kiosk={kiosk}
          onToggleKiosk={toggleKiosk}
        />
        <main className="shell__content">
          <div className="page-fade" key={active}>
            {active === "cockpit" && (
              <Cockpit
                onStatusChange={(status, isConnected) => {
                  setScenarioStatus(status);
                  setConnected(isConnected);
                }}
              />
            )}
            {active === "m4demo" && (
              <M4Demo
                onStatusChange={(status, isConnected) => {
                  setScenarioStatus(status);
                  setConnected(isConnected);
                }}
              />
            )}
            {active === "live" && (
              <LiveCluster
                onStatusChange={(status, isConnected) => {
                  setScenarioStatus(status);
                  setConnected(isConnected);
                }}
              />
            )}
            {active === "test" && <TestModels />}
            {active === "explainability" && <Explainability />}
            {active === "performance" && <Performance />}
          </div>
        </main>
      </div>
    </div>
  );
}
