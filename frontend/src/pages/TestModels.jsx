import { useState } from "react";
import { api } from "../lib/api";

const SERVICE_OPTIONS = [
  { value: "product-service-manual-0001", label: "product-service" },
  { value: "order-service-manual-0001", label: "order-service" },
  { value: "api-gateway-manual-0001", label: "api-gateway" },
  { value: "inventory-service-manual-0001", label: "inventory-service" },
];

const TERMINATED_OPTIONS = ["none", "Error", "OOMKilled"];
const EXCEPTION_OPTIONS = ["none", "client_error", "connection_lost", "session_expired", "kafka_coordination_error"];
const MEM_BUDGETS = ["200Mi", "300Mi", "400Mi"];

const DEFAULTS = {
  service_name: SERVICE_OPTIONS[0].value,
  cpu_usage_pct: 18,
  memory_usage_pct: 32,
  restart_count_delta: 0,
  http_p95_latency_ms: 180,
  log_error_count: 0,
  log_warn_count: 1,
  node_memory_available_pct: 45,
  jvm_heap_used_pct: 28,
  gc_pause_total_sec: 0.02,
  last_terminated_reason: "none",
  exception_signature: "none",
  mem_limit: "300Mi",
};

/** Construit un buffer synthétique de N points identiques : équivalent à "cette
 * mesure tient depuis un moment" (rolling std ~= 0, delta = 0). Suffisant pour
 * tester la réaction du modèle à une valeur donnée, pas pour rejouer une vraie
 * trajectoire — c'est à ça que sert le Cockpit. */
function buildHistory(form, n = 6) {
  const now = Date.now();
  const memLimitMi = parseInt(form.mem_limit, 10);
  const row = {
    run_id: "manual_test",
    service_name: form.service_name,
    node_name: "k8s2-worker1",
    profile: "manual",
    cpu_usage_pct: Number(form.cpu_usage_pct),
    memory_usage_pct: Number(form.memory_usage_pct),
    memory_working_set_bytes: (Number(form.memory_usage_pct) / 100) * memLimitMi * 1024 * 1024,
    restart_count_delta: Number(form.restart_count_delta),
    jvm_heap_used_pct: Number(form.jvm_heap_used_pct),
    gc_pause_total_sec: Number(form.gc_pause_total_sec),
    http_p95_latency_ms: Number(form.http_p95_latency_ms),
    db_active_connections_mongo: 2,
    db_query_duration_avg_ms: 12,
    db_query_duration_max_ms: 40,
    node_cpu_usage_pct: 20,
    node_load1: 0.6,
    node_memory_available_pct: Number(form.node_memory_available_pct),
    log_error_count: Number(form.log_error_count),
    log_warn_count: Number(form.log_warn_count),
    log_volume_total: 50,
    trace_error_span_ratio: 0,
    exception_signature: form.exception_signature,
    last_terminated_reason: form.last_terminated_reason,
    waiting_reason: "none",
    mem_limit_mi: form.mem_limit,
    mem_request_mi: form.mem_limit === "200Mi" ? "150Mi" : "200Mi",
  };
  return Array.from({ length: n }, (_, i) => ({
    ...row,
    timestamp: new Date(now - (n - 1 - i) * 30000).toISOString(),
  }));
}

function buildM4Series(base, pattern, n = 20) {
  const series = [];
  for (let i = 0; i < n; i++) {
    let v = base;
    if (pattern === "ramp") v = base + (i / n) * (95 - base);
    if (pattern === "spike") v = i === n - 1 ? 97 : base + (Math.random() - 0.5) * 3;
    if (pattern === "stable") v = base + (Math.random() - 0.5) * 3;
    series.push(Math.max(0, Math.min(100, v)));
  }
  return series;
}

function ResultCard({ title, subtitle, loading, error, result, render }) {
  return (
    <div className="panel testcard">
      <div className="testcard__header">
        <h3>{title}</h3>
        <span className="testcard__subtitle">{subtitle}</span>
      </div>
      <div className="testcard__body">
        {loading && <span className="testcard__hint">Appel de l'API…</span>}
        {error && <span className="testcard__error">{error}</span>}
        {!loading && !error && result && render(result)}
        {!loading && !error && !result && <span className="testcard__hint">Aucun test lancé.</span>}
      </div>
    </div>
  );
}

export default function TestModels() {
  const [form, setForm] = useState(DEFAULTS);
  const [m4Pattern, setM4Pattern] = useState("ramp");
  const [results, setResults] = useState({ m1: null, m2: null, m3: null, m4: null });
  const [loading, setLoading] = useState({});
  const [errors, setErrors] = useState({});

  const update = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  const runModel = async (key, fn) => {
    setLoading((l) => ({ ...l, [key]: true }));
    setErrors((e) => ({ ...e, [key]: null }));
    try {
      const res = await fn();
      setResults((r) => ({ ...r, [key]: res }));
    } catch (err) {
      setErrors((e) => ({ ...e, [key]: err.message }));
    } finally {
      setLoading((l) => ({ ...l, [key]: false }));
    }
  };

  const testAll = () => {
    const history = buildHistory(form);
    runModel("m1", () => api.predictM1(history));
    runModel("m2", () => api.predictM2(history));
    runModel("m3", () => api.predictM3(history));
    runModel("m4", () => api.predictM4(buildM4Series(Number(form.cpu_usage_pct), m4Pattern), "cpu_usage_pct"));
  };

  return (
    <div className="testpage">
      <section className="panel testform">
        <div className="testform__header">
          <span className="eyebrow">Test manuel</span>
          <h2>Composer une mesure</h2>
          <p className="testform__hint">
            Simule une mesure stable sur ce service (buffer de 6 points identiques) et l'envoie aux 4 modèles.
            Pour une vraie trajectoire dans le temps, utilise le Cockpit.
          </p>
        </div>

        <div className="testform__grid">
          <label className="field">
            <span>Service</span>
            <select value={form.service_name} onChange={update("service_name")}>
              {SERVICE_OPTIONS.map((s) => (
                <option key={s.value} value={s.value}>{s.label}</option>
              ))}
            </select>
          </label>

          <label className="field">
            <span>CPU usage (%) — {form.cpu_usage_pct}</span>
            <input type="range" min="0" max="100" value={form.cpu_usage_pct} onChange={update("cpu_usage_pct")} />
          </label>

          <label className="field">
            <span>Memory usage (%) — {form.memory_usage_pct}</span>
            <input type="range" min="0" max="100" value={form.memory_usage_pct} onChange={update("memory_usage_pct")} />
          </label>

          <label className="field">
            <span>JVM heap (%) — {form.jvm_heap_used_pct}</span>
            <input type="range" min="0" max="100" value={form.jvm_heap_used_pct} onChange={update("jvm_heap_used_pct")} />
          </label>

          <label className="field">
            <span>HTTP p95 latency (ms) — {form.http_p95_latency_ms}</span>
            <input type="range" min="0" max="2000" value={form.http_p95_latency_ms} onChange={update("http_p95_latency_ms")} />
          </label>

          <label className="field">
            <span>Node memory dispo (%) — {form.node_memory_available_pct}</span>
            <input type="range" min="0" max="100" value={form.node_memory_available_pct} onChange={update("node_memory_available_pct")} />
          </label>

          <label className="field">
            <span>Restarts (delta)</span>
            <input type="number" min="0" max="10" value={form.restart_count_delta} onChange={update("restart_count_delta")} />
          </label>

          <label className="field">
            <span>Erreurs de log</span>
            <input type="number" min="0" max="100" value={form.log_error_count} onChange={update("log_error_count")} />
          </label>

          <label className="field">
            <span>Dernier arrêt (pod)</span>
            <select value={form.last_terminated_reason} onChange={update("last_terminated_reason")}>
              {TERMINATED_OPTIONS.map((o) => <option key={o} value={o}>{o}</option>)}
            </select>
          </label>

          <label className="field">
            <span>Exception</span>
            <select value={form.exception_signature} onChange={update("exception_signature")}>
              {EXCEPTION_OPTIONS.map((o) => <option key={o} value={o}>{o}</option>)}
            </select>
          </label>

          <label className="field">
            <span>Budget mémoire (M3)</span>
            <select value={form.mem_limit} onChange={update("mem_limit")}>
              {MEM_BUDGETS.map((o) => <option key={o} value={o}>{o}</option>)}
            </select>
          </label>

          <label className="field">
            <span>Tendance CPU (M4)</span>
            <select value={m4Pattern} onChange={(e) => setM4Pattern(e.target.value)}>
              <option value="stable">Stable</option>
              <option value="ramp">Montée progressive</option>
              <option value="spike">Pic brutal</option>
            </select>
          </label>
        </div>

        <button className="btn btn--primary btn--wide" onClick={testAll}>
          ▶ Envoyer aux 4 modèles
        </button>
      </section>

      <section className="testpage__results">
        <ResultCard
          title="M1 — Détection"
          subtitle="Isolation Forest / LOF"
          loading={loading.m1}
          error={errors.m1}
          result={results.m1}
          render={(r) => (
            <>
              <strong className={r.smoothed_anomaly ? "text-alert" : "text-nominal"}>
                {r.smoothed_anomaly ? "Anomalie détectée" : "Comportement normal"}
              </strong>
              <span className="mono">score {r.anomaly_score} / seuil {r.threshold}</span>
              {r.smoothed_anomaly && r.top_features && (
                <div className="pipeline__explain-tags" style={{ marginTop: 8 }}>
                  {r.top_features.slice(0, 4).map((f) => (
                    <span key={f.feature} className="explaintag mono">
                      {f.feature} <strong>{f.z_score > 0 ? "+" : ""}{f.z_score}σ</strong>
                    </span>
                  ))}
                </div>
              )}
            </>
          )}
        />
        <ResultCard
          title="M2 — Classification"
          subtitle="Gradient Boosting"
          loading={loading.m2}
          error={errors.m2}
          result={results.m2}
          render={(r) => (
            <>
              <strong className={r.predicted_class === "none" ? "text-nominal" : "text-alert"}>
                {r.predicted_class.toUpperCase()}
              </strong>
              <span className="mono">confiance {(r.confidence * 100).toFixed(1)}%</span>
              <div className="testcard__probs">
                {Object.entries(r.probabilities).map(([cls, p]) => (
                  <div className="probrow" key={cls}>
                    <span className="mono">{cls}</span>
                    <div className="probrow__bar"><div style={{ width: `${p * 100}%` }} /></div>
                    <span className="mono">{(p * 100).toFixed(0)}%</span>
                  </div>
                ))}
              </div>
            </>
          )}
        />
        <ResultCard
          title="M3 — Prédiction TTF"
          subtitle="Gradient Boosting quantile"
          loading={loading.m3}
          error={errors.m3}
          result={results.m3}
          render={(r) =>
            r.error ? (
              <span className="testcard__error">{r.error}</span>
            ) : (
              <>
                <strong className={r.alert ? "text-critical" : "text-nominal"}>
                  {r.time_to_failure_display_sec.toFixed(0)}s avant panne
                </strong>
                <span className="mono">
                  sécurité {r.time_to_failure_safety_sec.toFixed(0)}s · seuil alerte {r.alert_threshold_sec}s
                </span>
              </>
            )
          }
        />
        <ResultCard
          title="M4 — Seuil dynamique"
          subtitle="ARIMA glissant"
          loading={loading.m4}
          error={errors.m4}
          result={results.m4}
          render={(r) =>
            r.status === "warmup" ? (
              <>
                <span className="testcard__hint">{r.message}</span>
                <span className="mono">seuil fixe (&gt;80%) : {r.fixed_alert ? "🔴 alerte" : "🟢 normal"}</span>
              </>
            ) : (
              <>
                <strong className={r.alert ? "text-alert" : "text-nominal"}>
                  {r.alert ? "Hors seuil dynamique" : "Dans le seuil dynamique"}
                </strong>
                <span className="mono">
                  actuel {r.actual}% · bande {r.dynamic_threshold_lower}–{r.dynamic_threshold_upper}%
                </span>
                <span className="mono">déviation {r.deviation_sigma > 0 ? "+" : ""}{r.deviation_sigma}σ</span>
                <span className="mono">seuil fixe (&gt;80%) : {r.fixed_alert ? "🔴 alerte" : "🟢 normal"}</span>
                {r.avoided_false_alarm && <span className="pipeline__stage-compare">✔ M4 a évité une fausse alerte du seuil fixe</span>}
                {r.missed_by_fixed && <span className="pipeline__stage-compare">⚡ M4 a détecté ce que le seuil fixe aurait raté</span>}
              </>
            )
          }
        />
      </section>
    </div>
  );
}
