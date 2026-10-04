const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";
const WS_BASE = API_BASE.replace(/^http/, "ws");

async function postJSON(path, body) {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.detail || `Erreur ${res.status}`);
  }
  return data;
}

async function postFile(path, file) {
  const formData = new FormData();
  formData.append("file", file);
  const res = await fetch(`${API_BASE}${path}`, { method: "POST", body: formData });
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.detail || `Erreur ${res.status}`);
  }
  return data;
}

async function getJSON(path) {
  const res = await fetch(`${API_BASE}${path}`);
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.detail || `Erreur ${res.status}`);
  }
  return data;
}

export const api = {
  health: () => getJSON("/health"),
  scenarios: () => getJSON("/scenarios"),
  m4DemoMeta: () => getJSON("/scenarios/m4-demo"),
  metrics: () => getJSON("/models/metrics"),
  explainability: () => getJSON("/models/explainability"),
  predictM1: (history) => postJSON("/m1/predict", { history }),
  predictM2: (history) => postJSON("/m2/predict", { history }),
  predictM3: (history) => postJSON("/m3/predict", { history }),
  predictM4: (metric_history, metric_name = "cpu_usage_pct") =>
    postJSON("/m4/predict", { metric_history, metric_name }),
  runPipeline: (history) => postJSON("/pipeline/run", { history }),
  uploadScenario: (file) => postFile("/scenario/upload", file),
  scenarioSocketUrl: () => `${WS_BASE}/ws/scenario`,
  liveSocketUrl: () => `${WS_BASE}/ws/live`,
  ingestStats: () => getJSON("/ingest/stats"),
};

export const FAULT_LABELS = {
  cpu_throttle: "CPU Throttle",
  crashloop: "CrashLoop",
  db_down: "DB Down",
  oom: "OOM Kill",
};

export const FAULT_DESCRIPTIONS = {
  cpu_throttle: "Quota CPU saturé — le pod est étranglé par Kubernetes",
  crashloop: "Le pod redémarre en boucle sans se stabiliser",
  db_down: "Base de données injoignable — cascade d'erreurs en aval",
  oom: "Fuite mémoire progressive jusqu'au OOM Kill",
};
