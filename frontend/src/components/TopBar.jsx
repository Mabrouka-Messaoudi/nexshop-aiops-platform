import { useEffect, useState } from "react";

export default function TopBar({ connected, statusLabel, statusTone, kiosk, onToggleKiosk }) {
  const [now, setNow] = useState(new Date());

  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  const time = now.toLocaleTimeString("fr-FR", { hour12: false });

  return (
    <header className="topbar">
      <div className="topbar__title">
        <h1>
          NexShop <span className="topbar__title-accent">AIOps</span>
        </h1>
        <span className="eyebrow">Command Center — PFE Monitoring Intelligent</span>
      </div>

      <div className="topbar__status">
        <div className={`statuschip statuschip--${statusTone}`}>
          <span className="statuschip__dot" />
          {statusLabel}
        </div>
        <div className="statuschip statuschip--neutral">
          <span className={`statuschip__dot ${connected ? "is-live" : ""}`} />
          {connected ? "API connectée" : "API déconnectée"}
        </div>
        <div className="topbar__clock mono">{time}</div>
        <button className="btn kiosk-toggle" onClick={onToggleKiosk} title="Mode présentation">
          {kiosk ? "⤡ Quitter" : "⤢ Présentation"}
        </button>
      </div>
    </header>
  );
}
