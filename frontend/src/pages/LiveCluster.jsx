import { useEffect, useMemo } from "react";
import { useLiveSocket } from "../lib/useLiveSocket";
import PipelineRail from "../components/PipelineRail";
import EventLog, { isNotable } from "../components/EventLog";

export default function LiveCluster({ onStatusChange }) {
  const live = useLiveSocket();

  useEffect(() => {
    onStatusChange?.(live.nRows > 0 ? "running" : "idle", live.connected);
  }, [live.nRows, live.connected, onStatusChange]);

  // La carte "chaîne de décision" montrait auparavant littéralement le DERNIER point
  // reçu, tous services confondus -- mais collect_once() trie les services par ordre
  // alphabétique, donc le dernier de chaque tick est presque toujours le même service
  // (souvent le plus calme, ex. zookeeper) : la carte affichait "normal" en boucle
  // même en pleine panne active sur un autre service, incohérent avec la Timeline en
  // dessous.
  //
  // Premier correctif : afficher le dernier événement "notable" (M1 anomalie OU M4
  // hors seuil), même critère que le filtre de la Timeline. Mais ça reste incomplet :
  // un point où M1 seul a réagi (M2 → "none") est TOUJOURS considéré notable, donc s'il
  // est légèrement plus récent qu'un vrai "oom (100%)" juste en dessous dans la
  // Timeline, c'est le point ennuyeux qui gagne -- carte et Timeline racontent alors
  // deux histoires différentes, vécu en pratique.
  //
  // Priorité correcte : d'abord le dernier point où M2 a vraiment classifié quelque
  // chose (pas "none"), puisque c'est ça le signal fort qu'on veut mettre en avant.
  // Seulement si aucun n'existe, on retombe sur "M1 a réagi" puis sur le plus récent.
  const displayStep = useMemo(() => {
    if (live.log.length === 0) return null;
    const classified = live.log.find((e) => e.m2 && e.m2.predicted_class !== "none");
    if (classified) return classified;
    return live.log.find(isNotable) ?? live.log[0];
  }, [live.log]);

  return (
    <div className="cockpit">
      <section className="panel livecluster__intro">
        <span className="eyebrow">Cluster réel — pas un rejeu</span>
        <h2>Flux en direct depuis collector_final.py</h2>
        <p>
          Ici, aucune donnée n'est pré-enregistrée : chaque mesure vient d'un vrai tick de
          collecte sur le cluster (<code>--live-push</code> activé côté collecteur), poussée
          en direct via <code>POST /ingest/tick</code> et diffusée ici via WebSocket. Pas de
          play/pause/vitesse — c'est le cluster qui dicte le rythme, pas nous.
        </p>
        <div className="livecluster__stats">
          <div className="livecluster__stat">
            <span className="eyebrow">Ticks reçus</span>
            <strong>{live.nTicks}</strong>
          </div>
          <div className="livecluster__stat">
            <span className="eyebrow">Lignes traitées</span>
            <strong>{live.nRows}</strong>
          </div>
          <div className="livecluster__stat">
            <span className="eyebrow">Connexion</span>
            <strong className={live.connected ? "text-nominal" : "text-critical"}>
              {live.connected ? "établie" : "coupée"}
            </strong>
          </div>
        </div>
      </section>

      {live.errorMsg && <div className="banner banner--error">{live.errorMsg}</div>}

      {live.nRows === 0 && !live.errorMsg && (
        <div className="banner banner--hint">
          En attente de données — lance <code>run_oom_scenario_v2.sh</code> (ou un autre
          scénario) avec <code>LIVE_PUSH=1</code> sur le cluster pour voir ce panneau
          s'animer.
        </div>
      )}

      <div className="cockpit__main">
        <PipelineRail step={displayStep} />
      </div>

      <EventLog log={live.log} blind raw />
    </div>
  );
}
