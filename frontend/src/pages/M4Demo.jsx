import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { useScenarioSocket } from "../lib/useScenarioSocket";
import M4DemoChart, { PHASE_COLORS, PHASE_LABELS } from "../components/M4DemoChart";

const SPEED_STEPS = [1, 5, 10, 25, 50];
const FIXED_THRESHOLD_PCT = 80;

const CONCEPT_STEPS = [
  { phase: "normal", threshold: "[40 – 48]", cpu: 45, verdict: "NORMAL", tone: "nominal" },
  { phase: "montee_charge", threshold: "[62 – 74]", cpu: 70, verdict: "NORMAL", tone: "nominal" },
  { phase: "blackfriday", threshold: "[86 – 96]", cpu: 91, verdict: "NORMAL", tone: "nominal" },
  { phase: "spike", threshold: "hors bande", cpu: 99, verdict: "ALERT", tone: "critical" },
  { phase: "recovery", threshold: "[45 – 52]", cpu: 47, verdict: "NORMAL", tone: "nominal" },
];

function statsByPhase(log) {
  const out = {};
  for (const entry of log) {
    const phase = entry.phase;
    out[phase] ??= { m4Alerts: 0, fixedAlerts: 0, total: 0 };
    out[phase].total += 1;
    if (entry.m4?.alert) out[phase].m4Alerts += 1;
    if (entry.m4?.fixed_alert) out[phase].fixedAlerts += 1;
  }
  return out;
}

export default function M4Demo({ onStatusChange }) {
  const socket = useScenarioSocket();
  const [speed, setSpeedState] = useState(10);
  const [meta, setMeta] = useState(null);

  useEffect(() => {
    api.m4DemoMeta().then(setMeta).catch(() => setMeta(null));
  }, []);

  useEffect(() => {
    onStatusChange?.(socket.status, socket.connected);
  }, [socket.status, socket.connected, onStatusChange]);

  const isRunning = socket.status === "running";
  const isPaused = socket.status === "paused";
  const isActive = isRunning || isPaused;
  const isComplete = socket.status === "complete";

  const handleSetSpeed = (s) => {
    setSpeedState(s);
    socket.setSpeed(s);
  };

  const current = socket.m4Demo ? socket.current : null;
  const m4 = current?.m4;
  const currentPhase = current?.phase;
  const stats = socket.m4Demo && (isComplete || isPaused) ? statsByPhase(socket.log) : null;

  const totalM4Alerts = stats ? Object.values(stats).reduce((a, s) => a + s.m4Alerts, 0) : null;
  const totalFixedAlerts = stats ? Object.values(stats).reduce((a, s) => a + s.fixedAlerts, 0) : null;
  const blackfridayStats = stats?.blackfriday;

  return (
    <div className="m4demo">
      <section className="panel m4demo__intro">
        <span className="eyebrow">Scénario dédié — M4 seul</span>
        <h2>Le seuil dynamique n'est pas un seuil fixe</h2>
        <p>
          Un CPU à 91% peut être <strong>normal</strong> un Black Friday et <strong>critique</strong> un
          mardi calme — ce n'est pas la valeur absolue qui compte, mais l'écart par rapport au contexte
          récent. M4 réajuste un ARIMA en continu sur les dernières minutes pour recalculer sa bande de
          confiance à chaque point, plutôt que de comparer à un seuil figé une fois pour toutes (par
          exemple "alerte si CPU &gt; {FIXED_THRESHOLD_PCT}%", affiché en pointillés sur le graphe).
        </p>
        {meta && (
          <span className="m4demo__meta mono">
            {meta.service_name} · {meta.metric} · {meta.n_points} points · {Object.keys(meta.phases).length} phases
          </span>
        )}
      </section>

      <section className="panel m4demo__concept">
        <span className="eyebrow">Principe</span>
        <div className="m4demo__concept-rail">
          <div className="m4demo__concept-node m4demo__concept-node--root">NexShop → M4</div>
          {CONCEPT_STEPS.map((s, i) => (
            <div className="m4demo__concept-group" key={s.phase}>
              <div className="m4demo__concept-arrow">↓</div>
              <div className="m4demo__concept-label" style={{ color: PHASE_COLORS[s.phase] }}>
                {PHASE_LABELS[s.phase]}
              </div>
              <div className="m4demo__concept-arrow">↓</div>
              <div className="m4demo__concept-detail mono">seuil {s.threshold}</div>
              <div className="m4demo__concept-arrow">↓</div>
              <div className="m4demo__concept-detail mono">CPU = {s.cpu}%</div>
              <div className="m4demo__concept-arrow">↓</div>
              <div className={`m4demo__concept-verdict tone-${s.tone}`}>{s.verdict}</div>
              {i < CONCEPT_STEPS.length - 1 && <div className="m4demo__concept-sep" />}
            </div>
          ))}
        </div>
      </section>

      <section className="panel m4demo__controls">
        <div className="controls__header">
          <span className="eyebrow">Rejeu live</span>
          <h2>Phases réelles rejouées point par point</h2>
        </div>
        <div className="controls__transport">
          <div className="transport-buttons">
            {!isActive ? (
              <button className="btn btn--primary" onClick={() => socket.startM4Demo(speed)} disabled={isRunning}>
                ▶ Lancer la démo M4
              </button>
            ) : !isRunning ? (
              <button className="btn btn--primary" onClick={socket.resume}>
                ▶ Reprendre
              </button>
            ) : (
              <button className="btn btn--primary" onClick={socket.pause}>
                ⏸ Pause
              </button>
            )}
            <button className="btn" onClick={socket.reset} disabled={!isActive && !isComplete}>
              ↺ Réinitialiser
            </button>
          </div>
          <div className="speed-control">
            <span className="eyebrow">Vitesse ×{speed}</span>
            <div className="speed-control__steps">
              {SPEED_STEPS.map((s) => (
                <button
                  key={s}
                  className={`speed-step ${speed === s ? "is-selected" : ""}`}
                  onClick={() => handleSetSpeed(s)}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        </div>
      </section>

      {socket.errorMsg && <div className="banner banner--error">{socket.errorMsg}</div>}

      {socket.m4Demo && (
        <section className="panel m4demo__live">
          <div className="m4demo__live-header">
            <span className="eyebrow">En direct</span>
            {currentPhase && (
              <span className="m4demo__phase-badge" style={{ borderColor: PHASE_COLORS[currentPhase] }}>
                <span className="m4demo__phase-dot" style={{ background: PHASE_COLORS[currentPhase] }} />
                {PHASE_LABELS[currentPhase] ?? currentPhase}
              </span>
            )}
          </div>

          <div className="m4demo__live-stats">
            <div className="m4demo__stat">
              <span className="eyebrow">CPU réel</span>
              <strong className="mono">{current ? `${current.cpu_usage_pct}%` : "—"}</strong>
            </div>
            <div className="m4demo__stat">
              <span className="eyebrow">Bande dynamique (IC 95%)</span>
              <strong className="mono">
                {m4?.status === "active"
                  ? `${m4.dynamic_threshold_lower}% – ${m4.dynamic_threshold_upper}%`
                  : m4?.status === "warmup"
                  ? "chauffe…"
                  : "—"}
              </strong>
            </div>
            <div className="m4demo__stat">
              <span className="eyebrow">Verdict M4</span>
              <strong className={m4?.alert ? "tone-critical" : "tone-nominal"}>
                {m4?.status === "active" ? (m4.alert ? "ALERT" : "NORMAL") : "—"}
              </strong>
            </div>
            <div className="m4demo__stat">
              <span className="eyebrow">Verdict seuil fixe (&gt;{FIXED_THRESHOLD_PCT}%)</span>
              <strong className={m4?.fixed_alert ? "tone-critical" : "tone-nominal"}>
                {m4 ? (m4.fixed_alert ? "ALERT" : "NORMAL") : "—"}
              </strong>
            </div>
          </div>

          {m4?.avoided_false_alarm && (
            <div className="banner banner--hint" style={{ marginTop: 0 }}>
              ✔ Ce point précis : M4 reste calme alors que le seuil fixe sonnerait — fausse alerte évitée.
            </div>
          )}

          <M4DemoChart log={socket.log} />

          <div className="m4chart-legend">
            {Object.entries(PHASE_LABELS).map(([k, label]) => (
              <span key={k} className="m4chart-legend__item">
                <span className="m4chart-legend__dot" style={{ background: PHASE_COLORS[k] }} />
                {label}
              </span>
            ))}
            <span className="m4chart-legend__item">
              <span className="m4chart-legend__dot m4chart-legend__dot--diamond" />
              fausse alerte évitée par M4
            </span>
          </div>
        </section>
      )}

      {stats && (
        <section className="panel m4demo__verify">
          <span className="eyebrow">Vérification</span>
          <h2>Alertes par phase — M4 vs seuil fixe (&gt;{FIXED_THRESHOLD_PCT}%)</h2>
          <div className="m4demo__verify-grid m4demo__verify-grid--compare">
            <div className="m4demo__verify-row m4demo__verify-row--header">
              <span>Phase</span>
              <span className="mono">M4</span>
              <span className="mono">seuil fixe</span>
            </div>
            {Object.entries(PHASE_LABELS).map(([phase, label]) => {
              const s = stats[phase];
              return (
                <div className="m4demo__verify-row" key={phase}>
                  <span style={{ color: PHASE_COLORS[phase] }}>{label}</span>
                  <span className="mono">{s ? `${s.m4Alerts} / ${s.total}` : "—"}</span>
                  <span className="mono">{s ? `${s.fixedAlerts} / ${s.total}` : "—"}</span>
                </div>
              );
            })}
            <div className="m4demo__verify-row m4demo__verify-row--total">
              <span>Total</span>
              <span className="mono">{totalM4Alerts}</span>
              <span className="mono">{totalFixedAlerts}</span>
            </div>
          </div>
          <p className="m4demo__verify-note">
            Le point essentiel : pendant le <strong>Black Friday soutenu</strong> (charge légitime la
            plus haute du scénario), M4 déclenche{" "}
            <strong>{blackfridayStats ? `${blackfridayStats.m4Alerts}/${blackfridayStats.total}` : "—"}</strong>{" "}
            alerte(s), contre <strong>{blackfridayStats ? `${blackfridayStats.fixedAlerts}/${blackfridayStats.total}` : "—"}</strong>{" "}
            pour un seuil fixe classique. Le seul vrai incident du scénario (le spike, au-delà même du
            niveau Black Friday) reste détecté par les deux — la différence se joue sur les fausses alertes
            évitées, pas sur la détection du vrai problème.
          </p>
        </section>
      )}
    </div>
  );
}
