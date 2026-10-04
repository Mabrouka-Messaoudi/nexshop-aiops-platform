import { useState } from "react";

function summarize(entry) {
  const parts = [];
  if (entry.m1?.smoothed_anomaly) {
    parts.push(`M1 anomalie (score ${entry.m1.anomaly_score.toFixed(2)})`);
  }
  if (entry.m2) {
    parts.push(`M2 → ${entry.m2.predicted_class} (${(entry.m2.confidence * 100).toFixed(0)}%)`);
  }
  if (entry.m3 && !entry.m3.error) {
    parts.push(`M3 TTF ${entry.m3.time_to_failure_safety_sec.toFixed(0)}s${entry.m3.alert ? " ⚠" : ""}`);
  }
  if (entry.m4?.status === "active" && entry.m4.alert) {
    parts.push(`M4 hors seuil dynamique`);
  }
  return parts.length ? parts.join(" · ") : "RAS — trafic nominal";
}

export function isNotable(entry) {
  return Boolean(entry.m1?.smoothed_anomaly || (entry.m4?.status === "active" && entry.m4.alert));
}

export default function EventLog({ log, blind, raw }) {
  const [onlyNotable, setOnlyNotable] = useState(raw);
  const rows = onlyNotable ? log.filter(isNotable) : log;

  return (
    <section className="panel eventlog">
      <div className="eventlog__header">
        <span className="eyebrow">03 — Journal Ops</span>
        <h2>
          Timeline
          {blind && <span className="blind-badge">🙈 aveugle</span>}
        </h2>
        {raw && (
          <label className="eventlog__filter">
            <input type="checkbox" checked={onlyNotable} onChange={(e) => setOnlyNotable(e.target.checked)} />
            <span>Événements notables uniquement</span>
          </label>
        )}
      </div>
      <div className="eventlog__list scrollpanel">
        {rows.length === 0 && <div className="eventlog__empty">Lance un scénario pour voir le journal se remplir.</div>}
        {rows.map((entry) => (
          <div key={`${entry.service_name}|${entry.timestamp}|${entry.step}`} className={`eventlog__row ${raw ? "eventlog__row--with-service" : ""}`}>
            <span className="mono eventlog__time">{entry.timestamp.split(" ")[1] ?? entry.timestamp}</span>
            {raw && <span className="mono eventlog__service">{entry.service_name.split("-")[0]}</span>}
            <span className="mono eventlog__step">t={entry.step}</span>
            <span className="eventlog__summary">{summarize(entry)}</span>
          </div>
        ))}
      </div>
    </section>
  );
}
