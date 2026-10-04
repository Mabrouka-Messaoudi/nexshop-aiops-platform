"""
Live Ingest Manager — le collecteur réel (collector_final.py, sur le cluster) pousse
ici ses mesures au fil de l'eau, à la place de relire un CSV après coup.

Principe : on réutilise EXACTEMENT la même fonction de pipeline que les rejeux
(_execute_pipeline_step de scenario_engine.py) -- le pipeline ne sait pas et ne doit
pas savoir si les données viennent d'un CSV rejoué ou d'un vrai cluster en train de
tomber en panne. C'est ce qui garantit que le comportement testé en démo (rejeu) et
le comportement en conditions réelles (ce module) sont rigoureusement identiques.

Honnêteté du pipeline, comme partout ailleurs dans ce projet : blind=True et
fault_type_for_smoothing=None systématiquement -- en production, personne ne sait à
l'avance quel type de panne va se produire. C'est même ICI que cette hypothèse
devient réellement vraie (dans les rejeux, blind=True est une simulation ; ici,
c'est simplement l'état réel des choses).

Un seul run à la fois est suivi (buffers/historiques au niveau module) : suffisant
pour une démo où un seul scénario tourne sur le cluster à un instant donné. Si
plusieurs run_id distincts arrivent en même temps, les buffers sont naturellement
séparés par (run_id, service_name) -- cf. ServiceBufferStore -- donc ça reste correct,
juste pas isolé "session par session" comme pour les rejeux pilotés par WebSocket.
"""

import logging
from collections import deque

from fastapi import WebSocket

from .buffers import ServiceBufferStore
from .scenario_engine import _execute_pipeline_step

logger = logging.getLogger("nexshop.live_ingest")

MAX_RECENT_RESULTS = 500  # gardé en mémoire pour qu'un client qui se connecte en cours de run rattrape un peu d'historique


class LiveIngestManager:
    def __init__(self):
        self._buffers = ServiceBufferStore()
        self._m1_history: dict = {}
        self._m4_history: dict = {}
        self._step_counter = 0
        self._clients: set[WebSocket] = set()
        self._recent_results: deque = deque(maxlen=MAX_RECENT_RESULTS)
        self._n_ticks_received = 0
        self._n_rows_received = 0

    @property
    def stats(self) -> dict:
        return {
            "n_ticks_received": self._n_ticks_received,
            "n_rows_received": self._n_rows_received,
            "n_connected_clients": len(self._clients),
            "known_services": sorted({k[1] for k in self._buffers._buffers.keys()}),
        }

    def register(self, websocket: WebSocket):
        self._clients.add(websocket)

    def unregister(self, websocket: WebSocket):
        self._clients.discard(websocket)

    def recent_results(self) -> list[dict]:
        """Pour qu'un client qui se connecte en cours de route voie un peu de contexte
        au lieu d'un écran vide."""
        return list(self._recent_results)

    def current_status(self) -> list[dict]:
        """État actuel du pipeline, un enregistrement PLAT par service (le plus
        récent connu) -- pensé pour être consommé tel quel par un panneau table
        Grafana via le plugin Infinity, sans transformation JSON supplémentaire
        côté dashboard. Contrairement à /ws/live (flux temps réel), c'est un
        instantané interrogeable en HTTP classique, adapté au polling périodique
        de Grafana plutôt qu'à une connexion persistante."""
        latest_per_service: dict[str, dict] = {}
        for r in self._recent_results:
            latest_per_service[r["service_name"]] = r  # le plus récent écrase l'ancien, l'ordre d'itération suit l'insertion

        rows = []
        for service, r in latest_per_service.items():
            m1 = r.get("m1") or {}
            m2 = r.get("m2") or {}
            m3 = r.get("m3") or {}
            m4 = r.get("m4") or {}
            rows.append({
                "service_name": service,
                "run_id": r.get("run_id"),
                "step": r.get("step"),
                "m1_anomaly_score": m1.get("anomaly_score"),
                "m1_smoothed_anomaly": m1.get("smoothed_anomaly"),
                "m2_predicted_class": m2.get("predicted_class") if m2 else None,
                "m2_confidence": m2.get("confidence") if m2 else None,
                "m2_critical_memory_safety_net": m2.get("critical_memory_safety_net") if m2 else None,
                "m3_time_to_failure_safety_sec": m3.get("time_to_failure_safety_sec") if m3 and not m3.get("error") else None,
                "m3_alert": m3.get("alert") if m3 and not m3.get("error") else None,
                "m4_status": m4.get("status") if m4 else None,
                "m4_alert": m4.get("alert") if m4 else None,
            })
        return rows

    def timeseries(self, service: str | None = None, limit: int = 500) -> list[dict]:
        """Historique COMPLET et PLAT, ordonné chronologiquement (le plus ancien en
        premier -- nécessaire pour qu'un panneau time series Grafana trace une
        courbe dans le bon sens). Contrairement à current_status() qui ne garde
        que le dernier point par service, ici chaque point de mesure devient sa
        propre ligne -- c'est ce qu'il faut pour visualiser l'évolution de chaque
        modèle dans le temps (score M1 vs seuil, TTF M3 qui descend, bande ARIMA de
        M4), pas juste un instantané figé."""
        rows = list(self._recent_results)
        if service:
            rows = [r for r in rows if r["service_name"] == service]
        rows = rows[-limit:]  # les plus récents dans la fenêtre demandée, mais toujours dans l'ordre chronologique d'origine

        out = []
        for r in rows:
            m1 = r.get("m1") or {}
            m2 = r.get("m2") or {}
            m3 = r.get("m3") or {}
            m4 = r.get("m4") or {}
            out.append({
                "timestamp": r.get("timestamp"),
                "step": r.get("step"),
                "service_name": r.get("service_name"),
                "run_id": r.get("run_id"),
                "m1_anomaly_score": m1.get("anomaly_score"),
                "m1_threshold": m1.get("threshold"),
                "m1_smoothed_anomaly": m1.get("smoothed_anomaly"),
                "m2_predicted_class": m2.get("predicted_class") if m2 else None,
                "m2_confidence": m2.get("confidence") if m2 else None,
                "m3_time_to_failure_safety_sec": m3.get("time_to_failure_safety_sec") if m3 and not m3.get("error") else None,
                "m3_time_to_failure_display_sec": m3.get("time_to_failure_display_sec") if m3 and not m3.get("error") else None,
                "m3_alert_threshold_sec": m3.get("alert_threshold_sec") if m3 and not m3.get("error") else None,
                "m4_actual": m4.get("actual") if m4 else None,
                "m4_forecast": m4.get("forecast") if m4 else None,
                "m4_lower": m4.get("dynamic_threshold_lower") if m4 else None,
                "m4_upper": m4.get("dynamic_threshold_upper") if m4 else None,
                "m4_fixed_threshold_pct": m4.get("fixed_threshold_pct") if m4 else None,
                "m4_status": m4.get("status") if m4 else None,
            })
        return out

    async def ingest_tick(self, rows: list[dict]) -> list[dict]:
        """Exécute le pipeline sur chaque ligne du tick (une par pod, comme envoyé par
        collector_final.py), diffuse les résultats aux clients connectés."""
        self._n_ticks_received += 1
        self._n_rows_received += len(rows)
        results = []
        for row in rows:
            if not row.get("service_name") or not row.get("run_id"):
                continue  # ligne incomplète, ignorée plutôt que de faire planter tout le tick
            try:
                result = _execute_pipeline_step(
                    row, self._step_counter, self._buffers, self._m1_history, self._m4_history,
                    blind=True, fault_type_for_smoothing=None,
                )
            except Exception:
                logger.exception("Erreur pipeline sur une ligne du tick live (service=%s)", row.get("service_name"))
                continue
            self._step_counter += 1
            self._recent_results.append(result)
            results.append(result)

        if results:
            await self._broadcast(results)
        return results

    async def _broadcast(self, results: list[dict]):
        dead = []
        for ws in list(self._clients):
            try:
                await ws.send_json({"event": "live_tick", "data": results})
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._clients.discard(ws)

    def reset(self):
        """Repart de zéro (nouveau run de démo) -- n'efface pas les clients connectés,
        juste l'état du pipeline."""
        self._buffers.reset()
        self._m1_history.clear()
        self._m4_history.clear()
        self._recent_results.clear()
        self._step_counter = 0
        self._n_ticks_received = 0
        self._n_rows_received = 0


# Instance unique partagée par toute l'application (importée par main.py).
live_manager = LiveIngestManager()
