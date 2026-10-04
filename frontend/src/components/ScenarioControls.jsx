import { useRef, useState } from "react";
import { FAULT_DESCRIPTIONS, FAULT_LABELS, api } from "../lib/api";

const FAULT_ORDER = ["cpu_throttle", "crashloop", "db_down", "oom"];
const SPEED_STEPS = [1, 5, 10, 25, 50];
const MODES = [
  { id: "demo", label: "Démo pédagogique" },
  { id: "mystery", label: "Mystère aveugle" },
  { id: "upload", label: "Injection réelle" },
];

export default function ScenarioControls({
  scenario, status, faultType, blind, raw, nServices, speed,
  onStart, onStartRandom, onStartUpload, onPause, onResume, onSetSpeed, onReset,
}) {
  const [mode, setMode] = useState("demo");
  const [uploadState, setUploadState] = useState({ status: "idle", info: null, error: null });
  const fileInputRef = useRef(null);
  const isRunning = status === "running";
  const isPaused = status === "paused";
  const isActive = isRunning || isPaused;

  const handleFileChange = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploadState({ status: "uploading", info: null, error: null });
    try {
      const info = await api.uploadScenario(file);
      setUploadState({ status: "ready", info, error: null });
    } catch (err) {
      setUploadState({ status: "idle", info: null, error: err.message });
    }
  };

  return (
    <section className="panel controls">
      <div className="controls__header">
        <span className="eyebrow">01 — Injecter un scénario</span>
        <h2>Choisir une panne réelle</h2>
        <div className="mode-switch">
          {MODES.map((m) => (
            <button
              key={m.id}
              className={`mode-switch__btn ${mode === m.id ? "is-selected" : ""}`}
              onClick={() => setMode(m.id)}
              disabled={isActive}
            >
              {m.label}
            </button>
          ))}
        </div>
      </div>

      {mode === "demo" && (
        <div className="controls__faults">
          {FAULT_ORDER.map((ft) => {
            const meta = scenario?.[ft];
            return (
              <button
                key={ft}
                className={`fault-btn ${faultType === ft ? "is-selected" : ""}`}
                onClick={() => onStart(ft)}
                disabled={isActive && faultType !== ft}
                title={FAULT_DESCRIPTIONS[ft]}
              >
                <span className="fault-btn__label">{FAULT_LABELS[ft]}</span>
                <span className="fault-btn__desc">{FAULT_DESCRIPTIONS[ft]}</span>
                {meta && <span className="fault-btn__meta mono">{meta.n_points} pts réels · {meta.service_name.split("-")[0]}</span>}
              </button>
            );
          })}
        </div>
      )}

      {mode === "mystery" && (
        <div className="mystery-panel">
          <p>
            Le type de panne est tiré au hasard <strong>côté serveur</strong>, sur un scénario déjà
            filtré au service concerné. Aucune étiquette n'est envoyée au frontend pendant le rejeu.
            Bon pour une démo pédagogique rapide — pour un vrai test à l'aveugle sur tout le cluster,
            utilise plutôt "Injection réelle".
          </p>
          <button className="btn btn--primary btn--wide" onClick={() => onStartRandom(speed)} disabled={isActive}>
            🎲 Injecter un scénario mystère
          </button>
        </div>
      )}

      {mode === "upload" && (
        <div className="upload-panel">
          <p>
            Dépose un run brut réel — la sortie directe de <code>collector_final.py</code> sur le
            cluster (tous les services, non filtré, comme dans le CSV que génère ton script bash).
            La plateforme le rejoue point par point, dans l'ordre exact de collecte, sans savoir
            quel service est visé. Le pipeline doit le découvrir lui-même.
          </p>
          <input
            ref={fileInputRef}
            type="file"
            accept=".csv"
            onChange={handleFileChange}
            disabled={isActive || uploadState.status === "uploading"}
            className="upload-panel__input"
          />
          {uploadState.status === "uploading" && <span className="testcard__hint">Envoi et validation du CSV…</span>}
          {uploadState.error && <span className="testcard__error">{uploadState.error}</span>}
          {uploadState.info && (
            <div className="upload-panel__info mono">
              {uploadState.info.n_points} points · {uploadState.info.n_services} services détectés
            </div>
          )}
          <button
            className="btn btn--primary btn--wide"
            onClick={() => onStartUpload(uploadState.info.dataset_id, speed)}
            disabled={isActive || uploadState.status !== "ready"}
          >
            🔬 Lancer l'investigation sur ce run
          </button>
        </div>
      )}

      {blind && isActive && (
        <div className="banner banner--hint" style={{ marginTop: 0 }}>
          🙈 Mode aveugle actif{raw ? ` — rejeu brut, ${nServices} services entrelacés` : ""} — rien n'est révélé sur cet écran.
        </div>
      )}

      <div className="controls__transport">
        <div className="transport-buttons">
          {!isRunning ? (
            <button className="btn btn--primary" onClick={onResume} disabled={!isPaused}>
              ▶ {isPaused ? "Reprendre" : "En attente"}
            </button>
          ) : (
            <button className="btn btn--primary" onClick={onPause}>
              ⏸ Pause
            </button>
          )}
          <button className="btn" onClick={onReset} disabled={!isActive && status !== "complete"}>
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
                onClick={() => onSetSpeed(s)}
              >
                {s}
              </button>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
