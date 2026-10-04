export const PHASE_COLORS = {
  normal: "var(--signal)",
  montee_charge: "var(--amber)",
  high_soutenu: "var(--amber)",
  montee_blackfriday: "var(--magenta)",
  blackfriday: "var(--magenta)",
  spike: "var(--red)",
  recovery: "var(--violet)",
};

export const PHASE_LABELS = {
  normal: "Trafic normal",
  montee_charge: "Montée de charge",
  high_soutenu: "Charge soutenue",
  montee_blackfriday: "Montée Black Friday",
  blackfriday: "Black Friday soutenu",
  spike: "Anomalie (au-delà du Black Friday)",
  recovery: "Recovery",
};

const FIXED_THRESHOLD_PCT = 80;

/** Rejoue le scénario M4 sous forme de graphe : métrique réelle (ligne), bande de
 * seuil dynamique ARIMA (aire), ligne de seuil fixe classique (pointillés), alertes
 * M4 (points rouges) vs alertes seuil fixe évitées par M4 (losanges ambre) -- preuve
 * visuelle directe que M4 reste calme là où un seuil fixe sonnerait pour rien. */
export default function M4DemoChart({ log }) {
  const data = [...log].reverse(); // le socket accumule le plus récent en tête

  if (data.length === 0) {
    return <div className="m4chart m4chart--empty">En attente du lancement du scénario…</div>;
  }

  const W = 900;
  const H = 260;
  const PAD_L = 34;
  const PAD_R = 12;
  const PAD_T = 16;
  const PAD_B = 22;
  const innerW = W - PAD_L - PAD_R;
  const innerH = H - PAD_T - PAD_B;

  const steps = data.map((d) => d.step);
  const minStep = Math.min(...steps);
  const maxStep = Math.max(...steps);
  const stepSpan = Math.max(maxStep - minStep, 1);

  const values = data
    .flatMap((d) => [d.cpu_usage_pct, d.m4?.dynamic_threshold_lower, d.m4?.dynamic_threshold_upper, FIXED_THRESHOLD_PCT])
    .filter((v) => typeof v === "number");
  const yMin = Math.max(0, Math.min(...values) - 8);
  const yMax = Math.min(100, Math.max(...values) + 8);
  const ySpan = Math.max(yMax - yMin, 1);

  const x = (step) => PAD_L + ((step - minStep) / stepSpan) * innerW;
  const y = (val) => PAD_T + innerH - ((val - yMin) / ySpan) * innerH;

  const activePoints = data.filter((d) => d.m4?.status === "active");
  const bandPath = activePoints.length
    ? `M ${activePoints.map((d) => `${x(d.step)},${y(d.m4.dynamic_threshold_upper)}`).join(" L ")} ` +
      `L ${[...activePoints].reverse().map((d) => `${x(d.step)},${y(d.m4.dynamic_threshold_lower)}`).join(" L ")} Z`
    : "";

  const linePath = `M ${data.map((d) => `${x(d.step)},${y(d.cpu_usage_pct)}`).join(" L ")}`;

  const phaseSegments = [];
  let segStart = 0;
  for (let i = 1; i <= data.length; i++) {
    if (i === data.length || data[i].phase !== data[segStart].phase) {
      phaseSegments.push({ start: data[segStart].step, end: data[i - 1].step, phase: data[segStart].phase });
      segStart = i;
    }
  }

  const alerts = data.filter((d) => d.m4?.alert);
  const avoided = data.filter((d) => d.m4?.avoided_false_alarm);
  const yTicks = [yMin, (yMin + yMax) / 2, yMax];

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="m4chart-svg" preserveAspectRatio="none">
      {phaseSegments.map((seg, i) => (
        <rect
          key={i}
          x={x(seg.start) - 1}
          y={PAD_T}
          width={Math.max(x(seg.end) - x(seg.start) + 2, 1)}
          height={innerH}
          fill={PHASE_COLORS[seg.phase] ?? "var(--text-faint)"}
          opacity={0.08}
        />
      ))}
      {bandPath && <path d={bandPath} fill="var(--signal)" opacity={0.14} />}
      <line
        x1={PAD_L} x2={W - PAD_R}
        y1={y(FIXED_THRESHOLD_PCT)} y2={y(FIXED_THRESHOLD_PCT)}
        stroke="var(--text-faint)" strokeWidth={1.2} strokeDasharray="5,4"
      />
      <text x={W - PAD_R - 2} y={y(FIXED_THRESHOLD_PCT) - 5} fontSize={9} fill="var(--text-faint)" fontFamily="var(--font-mono)" textAnchor="end">
        seuil fixe {FIXED_THRESHOLD_PCT}%
      </text>
      <path d={linePath} fill="none" stroke="var(--text)" strokeWidth={1.6} />
      {avoided.map((d) => (
        <rect key={`avoided-${d.step}`} x={x(d.step) - 4} y={y(d.cpu_usage_pct) - 4} width={8} height={8}
          fill="var(--amber)" opacity={0.85} transform={`rotate(45 ${x(d.step)} ${y(d.cpu_usage_pct)})`} />
      ))}
      {alerts.map((d) => (
        <circle key={d.step} cx={x(d.step)} cy={y(d.cpu_usage_pct)} r={5} fill="var(--red)" stroke="var(--ink)" strokeWidth={1} />
      ))}
      {yTicks.map((v, i) => (
        <text key={i} x={4} y={y(v) + 3} fontSize={9} fill="var(--text-faint)" fontFamily="var(--font-mono)">
          {Math.round(v)}%
        </text>
      ))}
      <line x1={PAD_L} y1={PAD_T + innerH} x2={W - PAD_R} y2={PAD_T + innerH} stroke="var(--line)" strokeWidth={1} />
    </svg>
  );
}
