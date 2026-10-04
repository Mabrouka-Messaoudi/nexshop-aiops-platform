const STAGES = [
  { id: "m1", label: "M1", name: "Détection", desc: "Isolation Forest / LOF" },
  { id: "m2", label: "M2", name: "Classification", desc: "Gradient Boosting" },
  { id: "m3", label: "M3", name: "Prédiction", desc: "TTF (quantile GB)" },
  { id: "m4", label: "M4", name: "Seuil dynamique", desc: "ARIMA glissant" },
];

function stageState(stageId, result) {
  if (!result) return { tone: "idle", headline: "—", detail: "en attente de données" };

  if (stageId === "m1") {
    return {
      tone: result.smoothed_anomaly ? "alert" : "nominal",
      headline: result.smoothed_anomaly ? "Anomalie détectée" : "Comportement normal",
      detail: `score ${result.anomaly_score.toFixed(2)} / seuil ${result.threshold.toFixed(2)}`,
    };
  }
  if (stageId === "m2") {
    if (!result) return { tone: "off", headline: "Non déclenché", detail: "M1 n'a rien signalé" };
    const safetyNet = result.critical_memory_safety_net;
    return {
      // Le garde-fou prime sur le ton visuel même si le modèle dit "none" -- jamais
      // afficher vert/normal quand la mémoire brute dépasse 90% de la limite,
      // peu importe ce que M2 a appris à reconnaître comme motif.
      tone: safetyNet ? "critical" : (result.predicted_class === "none" ? "nominal" : "alert"),
      headline: result.predicted_class.toUpperCase(),
      detail: `confiance ${(result.confidence * 100).toFixed(1)}%`,
      compare: null,
    };
  }
  if (stageId === "m3") {
    if (!result) return { tone: "off", headline: "Non applicable", detail: "hors trajectoire OOM" };
    if (result.error) return { tone: "off", headline: "Indisponible", detail: result.error };
    return {
      tone: result.alert ? "critical" : "nominal",
      headline: `${result.time_to_failure_display_sec.toFixed(0)}s avant panne`,
      detail: `sécurité ${result.time_to_failure_safety_sec.toFixed(0)}s (seuil ${result.alert_threshold_sec}s)`,
    };
  }
  if (stageId === "m4") {
    if (result.status === "warmup") {
      return {
        tone: "off",
        headline: "Chauffe",
        detail: result.message,
        compare: result.fixed_alert ? "Seuil fixe (>80%) déjà 🔴 — M4 pas encore actif" : null,
      };
    }
    if (result.status === "missing_data") {
      return {
        tone: "off",
        headline: "Métrique manquante",
        detail: result.message,
        compare: null,
      };
    }
    if (result.status === "fit_failed") {
      return {
        tone: "off",
        headline: "Ajustement ARIMA échoué",
        detail: `Dernière valeur connue : ${result.actual}% — pas de bande de confiance ce cycle`,
        compare: null,
      };
    }
    let compare = null;
    if (result.avoided_false_alarm) compare = "✔ M4 a évité une fausse alerte que le seuil fixe aurait déclenchée";
    else if (result.missed_by_fixed) compare = "⚡ M4 a détecté ce que le seuil fixe aurait raté";
    else if (result.fixed_alert === result.alert) compare = `Seuil fixe (>80%) d'accord : ${result.fixed_alert ? "🔴" : "🟢"}`;
    return {
      tone: result.alert ? "alert" : "nominal",
      headline: result.alert ? "Hors seuil dynamique" : "Dans le seuil dynamique",
      detail: `${result.actual}% (bande ${result.dynamic_threshold_lower}–${result.dynamic_threshold_upper}%)`,
      compare,
    };
  }
  return { tone: "idle", headline: "—", detail: "" };
}

export default function PipelineRail({ step }) {
  const results = {
    m1: step?.m1 ?? null,
    m2: step?.m2 ?? null,
    m3: step?.m3 ?? null,
    m4: step?.m4 ?? null,
  };

  const affectedService =
    results.m2 && results.m2.predicted_class !== "none" ? step?.service_name : null;
  const observedService = step?.service_name ?? null;

  return (
    <section className="panel pipeline">
      <div className="pipeline__header">
        <span className="eyebrow">02 — Chaîne de décision</span>
        <h2>Pipeline M1 → M2 → M3 → M4</h2>
        {affectedService ? (
          <span className="pipeline__affected-service mono">
            Service affecté : <strong>{affectedService}</strong>
          </span>
        ) : (
          observedService && (
            <span className="pipeline__affected-service mono">
              Service observé : <strong>{observedService}</strong>
            </span>
          )
        )}
      </div>

      <div className="pipeline__rail" key={step?.step ?? "idle"}>
        {STAGES.map((stage, i) => {
          const result = stage.id === "m1" ? results.m1 : results[stage.id];
          const active = stage.id === "m1" ? true : Boolean(result);
          const st = stageState(stage.id, result);
          return (
            <div className="pipeline__stage-wrap" key={stage.id}>
              <div className={`pipeline__stage tone-${st.tone}`}>
                <div className="pipeline__stage-top">
                  <span className="pipeline__stage-tag mono">{stage.label}</span>
                  <span className={`pipeline__stage-pulse ${active && step ? "is-pulsing" : ""}`} />
                </div>
                <h3>{stage.name}</h3>
                <span className="pipeline__stage-desc">{stage.desc}</span>
                <div className="pipeline__stage-result">
                  <strong>{st.headline}</strong>
                  <span className="mono">{st.detail}</span>
                  {st.compare && <span className="pipeline__stage-compare">{st.compare}</span>}
                </div>
              </div>
              {i < STAGES.length - 1 && (
                <div className={`pipeline__link ${step ? "is-flowing" : ""}`}>
                  <span className="pipeline__link-packet" />
                </div>
              )}
            </div>
          );
        })}
      </div>

      {results.m1?.top_features && results.m1.smoothed_anomaly && (
        <div className="pipeline__explain">
          <span className="eyebrow">Pourquoi M1 a réagi (z-score par feature, ce point précis)</span>
          <div className="pipeline__explain-tags">
            {results.m1.top_features.map((f) => (
              <span key={f.feature} className="explaintag mono">
                {f.feature} <strong>{f.z_score > 0 ? "+" : ""}{f.z_score}σ</strong>
              </span>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
