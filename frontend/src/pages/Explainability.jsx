import { useEffect, useState } from "react";
import { api } from "../lib/api";

function ImportanceBar({ feature, importance, max }) {
  return (
    <div className="metricbar">
      <div className="metricbar__label">
        <span className="mono">{feature}</span>
        <span className="mono">{(importance * 100).toFixed(1)}%</span>
      </div>
      <div className="metricbar__track">
        <div className="metricbar__fill tone-violet" style={{ width: `${(importance / max) * 100}%` }} />
      </div>
    </div>
  );
}

export default function Explainability() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.explainability().then(setData).catch((e) => setError(e.message));
  }, []);

  if (error) return <div className="banner banner--error">{error}</div>;
  if (!data) return <div className="testcard__hint">Chargement…</div>;

  const m2Max = Math.max(...data.M2.top_features.map((f) => f.importance));
  const m3Max = Math.max(...data.M3.top_features.map((f) => f.importance));

  return (
    <div className="explainpage">
      <p className="explainpage__intro">
        Pourquoi chaque modèle décide ce qu'il décide — pas une boîte noire. La méthode diffère
        selon le type de modèle : importance globale pour les modèles à arbres (M2, M3),
        explication par mesure pour M1 (visible en direct dans le Cockpit) et déviation
        statistique pour M4 (univarié par nature).
      </p>

      <div className="explainpage__grid">
        <section className="panel perfcard">
          <span className="eyebrow">M1 — Détection d'anomalie</span>
          <h2>{data.M1.method}</h2>
          <p className="perfcard__notes">{data.M1.explanation}</p>
          <div className="banner banner--hint">
            Lance un scénario dans le Cockpit : chaque alerte M1 y affiche les 5 features au
            z-score le plus élevé pour ce point précis.
          </div>
        </section>

        <section className="panel perfcard">
          <span className="eyebrow">M2 — Classification de panne</span>
          <h2>{data.M2.method}</h2>
          <div className="perfcard__bars">
            {data.M2.top_features.map((f) => (
              <ImportanceBar key={f.feature} feature={f.feature} importance={f.importance} max={m2Max} />
            ))}
          </div>
        </section>

        <section className="panel perfcard">
          <span className="eyebrow">M3 — Prédiction Time-To-Failure</span>
          <h2>{data.M3.method}</h2>
          <div className="perfcard__bars">
            {data.M3.top_features.map((f) => (
              <ImportanceBar key={f.feature} feature={f.feature} importance={f.importance} max={m3Max} />
            ))}
          </div>
        </section>

        <section className="panel perfcard">
          <span className="eyebrow">M4 — Seuils dynamiques</span>
          <h2>{data.M4.method}</h2>
          <p className="perfcard__notes">{data.M4.explanation}</p>
          <div className="banner banner--hint">
            Chaque alerte M4 (Cockpit ou test manuel) affiche sa déviation en écarts-types
            par rapport à la prévision ARIMA du moment.
          </div>
        </section>
      </div>
    </div>
  );
}
