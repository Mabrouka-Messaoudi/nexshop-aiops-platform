import { useEffect, useRef, useState } from "react";
import { api } from "./api";

const MAX_LOG = 500;
const RECONNECT_DELAY_MS = 3000;

/** Connexion au flux live du cluster réel. Contrairement à useScenarioSocket, il n'y
 * a pas de play/pause/vitesse ici -- c'est collector_final.py, sur le vrai cluster,
 * qui dicte le rythme. Chaque message "live_tick" contient un batch de résultats
 * (une ligne par pod collecté à ce tick), pas un point à la fois.
 *
 * Ce canal peut rester silencieux longtemps (attente d'un vrai run sur le cluster) --
 * contrairement à /ws/scenario qui streame en continu pendant un rejeu. Certains
 * composants réseau intermédiaires (load balancer/proxy GCP) peuvent fermer une
 * connexion WebSocket jugée inactive ; on se reconnecte donc automatiquement plutôt
 * que d'abandonner et de laisser un message d'erreur permanent à l'écran. */
export function useLiveSocket() {
  const wsRef = useRef(null);
  const reconnectTimerRef = useRef(null);
  const mountedRef = useRef(true);
  // Le backend renvoie tout son historique récent ("live_backfill") à CHAQUE
  // reconnexion -- sur un run long avec une connexion instable (plusieurs
  // reconnexions automatiques), le même backfill peut arriver plusieurs fois.
  // Sans déduplication, ça produit à la fois des entrées dupliquées ET un
  // désordre visuel : `entry.step` sert de clé React dans EventLog, et des
  // clés dupliquées cassent la réconciliation de React (mauvais placement/
  // réutilisation des lignes). On retient les clés déjà vues pour ignorer
  // silencieusement tout doublon, peu importe combien de fois il revient.
  // Clé composite (service + timestamp + step), pas `step` seul : le collecteur
  // redémarre son compteur `step` à chaque nouvelle phase (pre_fault/during_fault/
  // recovery = nouveau process Python), donc un step bas peut légitimement se
  // répéter d'une phase à l'autre -- s'y fier seul rejetterait à tort de vraies
  // nouvelles lignes.
  const seenKeysRef = useRef(new Set());
  const [connected, setConnected] = useState(false);
  const [current, setCurrent] = useState(null); // dernier résultat reçu (n'importe quel service)
  const [log, setLog] = useState([]); // le plus récent en tête
  const [nTicks, setNTicks] = useState(0);
  const [nRows, setNRows] = useState(0);
  const [errorMsg, setErrorMsg] = useState(null);

  useEffect(() => {
    mountedRef.current = true;

    const connect = () => {
      const ws = new WebSocket(api.liveSocketUrl());
      wsRef.current = ws;

      ws.onopen = () => {
        setConnected(true);
        setErrorMsg(null);
      };

      ws.onclose = () => {
        setConnected(false);
        if (mountedRef.current) {
          // Reconnexion automatique -- une coupure réseau (ou un proxy qui referme
          // une connexion inactive) ne doit pas être une fin définitive.
          reconnectTimerRef.current = setTimeout(connect, RECONNECT_DELAY_MS);
        }
      };

      ws.onerror = () => {
        // Une erreur veut dire, par définition, que la connexion n'est pas saine --
        // on ne doit jamais laisser "connected" à true en même temps qu'un message
        // d'erreur affiché, même si l'événement "close" n'est pas encore arrivé.
        setConnected(false);
        setErrorMsg("Connexion au flux live impossible — nouvelle tentative dans quelques secondes...");
      };

      ws.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        if (msg.event === "ping") return; // signal de vie du serveur, rien à afficher
        if (msg.event === "live_backfill" || msg.event === "live_tick") {
          const results = msg.data;
          if (!results || results.length === 0) return;

          // Ignore tout ce qu'on a déjà vu (cf. commentaire sur seenKeysRef) --
          // un backfill répété ne doit ajouter aucune ligne déjà connue.
          const freshResults = results.filter((r) => {
            const key = `${r.service_name}|${r.timestamp}|${r.step}`;
            if (seenKeysRef.current.has(key)) return false;
            seenKeysRef.current.add(key);
            return true;
          });
          if (freshResults.length === 0) return;

          setCurrent(freshResults[freshResults.length - 1]);
          setLog((prev) => [...freshResults].reverse().concat(prev).slice(0, MAX_LOG));
          if (msg.event === "live_tick") {
            setNTicks((n) => n + 1);
          }
          setNRows((n) => n + freshResults.length);
          setErrorMsg(null);
        }
      };
    };

    connect();

    return () => {
      mountedRef.current = false;
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
      wsRef.current?.close();
    };
  }, []);

  return { connected, current, log, nTicks, nRows, errorMsg };
}
