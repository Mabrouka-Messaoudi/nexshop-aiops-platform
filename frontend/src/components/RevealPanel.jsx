import { FAULT_LABELS } from "../lib/api";

/** Classement des services par nombre de classifications M2 "non none" -- c'est le
 * pipeline qui désigne lui-même son suspect principal, à partir de ses propres
 * décisions, pas d'une info qu'on lui aurait donnée. */
function rankSuspects(log) {
  const bySvc = {};
  for (const entry of log) {
    if (!entry.m2 || entry.m2.predicted_class === "none") continue;
    const svc = entry.service_name;
    bySvc[svc] ??= {};
    bySvc[svc][entry.m2.predicted_class] = (bySvc[svc][entry.m2.predicted_class] || 0) + 1;
  }
  const ranked = Object.entries(bySvc).map(([svc, counts]) => {
    const [cls, count] = Object.entries(counts).sort((a, b) => b[1] - a[1])[0];
    const total = Object.values(counts).reduce((a, b) => a + b, 0);
    return { service: svc, cls, count, total };
  });
  return ranked.sort((a, b) => b.count - a.count);
}

export default function RevealPanel({ revealed, log, raw, onReveal }) {
  const suspects = rankSuspects(log);
  const top = suspects[0];
  const anomalyDetected = log.some((e) => e.m1?.smoothed_anomaly);
  const truthServiceType = revealed?.service_name?.split("-")[0];
  const topServiceType = top?.service.split("-")[0];
  const isMatch = top && revealed?.available && top.cls === revealed.fault_type && topServiceType === truthServiceType;

  return (
    <section className="panel revealpanel">
      <div className="revealpanel__header">
        <span className="eyebrow">04 — Verdict</span>
        <h2>Diagnostic du pipeline vs vérité terrain</h2>
      </div>

      <div className="revealpanel__diagnosis">
        <span className="revealpanel__diagnosis-label">
          {raw ? "Suspect principal désigné par le pipeline, à l'aveugle :" : "Ce que le pipeline a conclu, à l'aveugle :"}
        </span>
        {!anomalyDetected ? (
          <strong className="text-nominal">Aucune anomalie détectée — trafic jugé normal</strong>
        ) : top ? (
          <>
            <strong className="text-alert">
              {top.service}
              <span className="mono"> — {FAULT_LABELS[top.cls] ?? top.cls.toUpperCase()} ({top.count}/{top.total} points)</span>
            </strong>
            {raw && suspects.length > 1 && (
              <div className="revealpanel__runners-up">
                {suspects.slice(1, 4).map((s) => (
                  <span key={s.service} className="mono">
                    {s.service.split("-")[0]}: {FAULT_LABELS[s.cls] ?? s.cls} ({s.count})
                  </span>
                ))}
              </div>
            )}
          </>
        ) : (
          <strong className="text-alert">Anomalie détectée (M1), classification non concluante</strong>
        )}
      </div>

      {!revealed || !revealed.available ? (
        <button className="btn btn--primary btn--wide" onClick={onReveal}>
          🔓 Révéler la vérité terrain
        </button>
      ) : (
        <div className="revealpanel__truth">
          <div className="revealpanel__truth-row">
            <span>Vérité terrain :</span>
            <strong>{FAULT_LABELS[revealed.fault_type] ?? revealed.fault_type}</strong>
            <span className="mono">({truthServiceType} · {revealed.run_id})</span>
          </div>
          <div className={`revealpanel__verdict ${isMatch ? "is-match" : "is-mismatch"}`}>
            {isMatch
              ? "✔ Le pipeline a correctement identifié le service et le type de panne, sans jamais les avoir vus à l'avance."
              : "✘ Diagnostic partiel ou incorrect sur ce run — bon exemple à creuser devant le jury."}
          </div>
        </div>
      )}
    </section>
  );
}
