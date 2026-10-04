import { useEffect, useState } from "react";
import { api } from "../lib/api";

function Bar({ label, value, max = 100, tone = "signal" }) {
  return (
    <div className="metricbar">
      <div className="metricbar__label">
        <span>{label}</span>
        <span className="mono">{value.toFixed(1)}%</span>
      </div>
      <div className="metricbar__track">
        <div className={`metricbar__fill tone-${tone}`} style={{ width: `${(value / max) * 100}%` }} />
      </div>
    </div>
  );
}

export default function Performance() {
  const [metrics, setMetrics] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.metrics().then(setMetrics).catch((e) => setError(e.message));
  }, []);

  if (error) return <div className="banner banner--error">{error}</div>;
  if (!metrics) return <div className="testcard__hint">Chargement des métriques…</div>;

  return (
    <div className="perfpage">
      <section className="panel perfcard">
        <span className="eyebrow">M1 — Détection d'anomalie</span>
        <h2>{metrics.M1.model_chosen}</h2>
        <p className="perfcard__notes">{metrics.M1.notes}</p>
        <div className="perfcard__bars">
          {Object.entries(metrics.M1.recall_by_fault_type_pct).map(([label, v]) => (
            <Bar key={label} label={`Rappel — ${label}`} value={v} tone="signal" />
          ))}
        </div>
        <div className="perfcard__foot mono">
          Seuil : {metrics.M1.threshold_method} · Lissage : {metrics.M1.temporal_smoothing}
        </div>
      </section>

      <section className="panel perfcard">
        <span className="eyebrow">M2 — Classification de panne</span>
        <h2>{metrics.M2.model_chosen}</h2>
        <div className="perfcard__stats">
          <div className="stat"><strong>{metrics.M2.final_accuracy_pct}%</strong><span>Accuracy</span></div>
          <div className="stat"><strong>{metrics.M2.final_f1_macro_pct}%</strong><span>F1 macro</span></div>
          <div className="stat"><strong>{metrics.M2.test_set_size}</strong><span>Lignes de test</span></div>
        </div>
        <div className="perfcard__bars">
          {Object.entries(metrics.M2.per_class_f1_pct).map(([label, v]) => (
            <Bar key={label} label={`F1 — ${label}`} value={v} tone="violet" />
          ))}
        </div>
        <p className="perfcard__notes">{metrics.M2.notes}</p>
      </section>

      <section className="panel perfcard">
        <span className="eyebrow">M3 — Prédiction Time-To-Failure</span>
        <h2>{metrics.M3.model_chosen}</h2>
        <div className="perfcard__stats">
          <div className="stat"><strong>{metrics.M3.point_model_mae_sec}s</strong><span>MAE</span></div>
          <div className="stat"><strong>{metrics.M3.point_model_r2}</strong><span>R²</span></div>
          <div className="stat"><strong>{metrics.M3.alert_threshold_sec}s</strong><span>Seuil alerte</span></div>
        </div>
        <div className="perfcard__scenarios">
          {metrics.M3.demo_scenarios.map((s) => (
            <div key={s.scenario} className="scenariorow">
              <span>{s.scenario}</span>
              <span className="mono">+{s.lead_time_sec}s d'avance — {s.result}</span>
            </div>
          ))}
        </div>
        <p className="perfcard__notes">{metrics.M3.notes}</p>
      </section>

      <section className="panel perfcard">
        <span className="eyebrow">M4 — Seuils dynamiques</span>
        <h2>{metrics.M4.model_chosen}</h2>
        <div className="perfcard__compare">
          <div className="comparebar">
            <span>Seuil fixe</span>
            <div className="comparebar__track">
              <div className="comparebar__fill tone-critical" style={{ width: `${metrics.M4.false_alarm_rate_fixed_threshold_pct}%` }} />
            </div>
            <span className="mono">{metrics.M4.false_alarm_rate_fixed_threshold_pct}% fausses alertes</span>
          </div>
          <div className="comparebar">
            <span>ARIMA (M4)</span>
            <div className="comparebar__track">
              <div className="comparebar__fill tone-signal" style={{ width: `${metrics.M4.false_alarm_rate_arima_pct}%` }} />
            </div>
            <span className="mono">{metrics.M4.false_alarm_rate_arima_pct}% fausses alertes</span>
          </div>
        </div>
        <div className="perfcard__foot mono">
          Amélioration : ×{metrics.M4.improvement_factor} moins de fausses alertes · couverture in-sample {metrics.M4.in_sample_coverage_pct}%
        </div>
        <p className="perfcard__notes">{metrics.M4.notes}</p>
      </section>
    </div>
  );
}
