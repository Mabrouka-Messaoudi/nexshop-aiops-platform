"""
NexShop AIOps Command Center — Backend FastAPI

Expose les 4 modèles (M1 détection, M2 classification, M3 prédiction, M4 seuils
dynamiques) de deux façons :
  - endpoints REST indépendants, pour un test manuel modèle par modèle (onglet "Tester
    un modèle" du frontend)
  - un WebSocket de rejeu de scénario, pour la démo live pilotée (cockpit + pipeline)

Lancer en local :
    uvicorn app.main:app --reload --port 8000
"""

import asyncio
import json
import logging
import os
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import m1_anomaly, m2_classification, m3_prediction, m4_threshold
from .live_ingest import live_manager
from .m4_demo_engine import M4DemoPlayer
from .schemas import HistoryRequest, M4Request, ScenarioStartRequest
from .scenario_engine import SCENARIOS, RawRunPlayer, ScenarioPlayer, save_uploaded_csv, uploaded_csv_path
from .scenario_session import ScenarioSession, _send_json_safe

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nexshop.api")

DATA_DIR = Path(__file__).parent.parent / "data"

app = FastAPI(
    title="NexShop AIOps Command Center",
    description="API d'inférence des 4 modèles AIOps (M1-M4) + moteur de rejeu de scénario pour la démo.",
    version="1.0.0",
)

# En dev, le frontend React (Vite) tourne sur un port différent -> CORS ouvert.
# À restreindre à l'origine exacte du frontend avant tout déploiement au-delà du poste de démo.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_metrics_cache = json.load(open(DATA_DIR / "models_metrics.json"))

# Jeton partagé optionnel pour protéger /ingest/tick (le collecteur tourne sur le
# cluster, potentiellement joignable par NodePort -- un jeton simple évite que
# n'importe qui puisse injecter des données dans le pipeline live). Vide = désactivé
# (pratique en dev local avant le déploiement k8s).
INGEST_TOKEN = os.environ.get("INGEST_TOKEN", "")


class IngestTickRequest(BaseModel):
    rows: list[dict]


# ---------------------------------------------------------------------------
# Santé / métadonnées
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok", "models_loaded": ["M1", "M2", "M3", "M4"]}


@app.get("/models/metrics")
def models_metrics():
    """Métriques réelles des 4 modèles (issues des notebooks d'évaluation), pour
    l'onglet Performance & Explicabilité de la démo."""
    return _metrics_cache


@app.get("/models/explainability")
def models_explainability():
    """Sur quoi chaque modèle s'appuie pour décider. M1 : explication PAR INSTANCE
    (z-scores de la dernière prédiction faite, cf. /m1/predict) -- ce endpoint ne
    renvoie que la méthode, pas un résultat figé. M2/M3 : importance GLOBALE des
    features (feature_importances_ du modèle entraîné, calculée une fois). M4 :
    pas de notion de feature importance (modèle univarié réajusté en continu) --
    l'explication est la déviation en écarts-types par rapport à la prévision."""
    return {
        "M1": {
            "method": "Z-score par instance",
            "explanation": (
                "LOF/Isolation Forest ne fournit pas d'importance de feature globale. "
                "Chaque prédiction /m1/predict renvoie plutôt 'top_features' : les 5 "
                "features avec le plus grand écart-type standardisé pour CE point précis "
                "— la vraie réponse à 'pourquoi ce point-là'."
            ),
        },
        "M2": {
            "method": "Feature importance globale (Gradient Boosting)",
            "top_features": m2_classification._TOP_GLOBAL_FEATURES,
        },
        "M3": {
            "method": "Feature importance globale (Gradient Boosting quantile)",
            "top_features": m3_prediction._TOP_GLOBAL_FEATURES,
        },
        "M4": {
            "method": "Déviation en écarts-types",
            "explanation": (
                "Modèle univarié (une seule métrique à la fois) réajusté en continu -- pas "
                "de notion de feature importance. Chaque prédiction /m4/predict renvoie "
                "'deviation_sigma' : de combien d'écarts-types la valeur observée s'écarte "
                "de la prévision ARIMA."
            ),
        },
    }


@app.get("/scenarios")
def list_scenarios():
    """Scénarios de panne réels disponibles pour le rejeu (métadonnées + longueur)."""
    out = []
    for fault_type, filename in SCENARIOS.items():
        player = ScenarioPlayer(fault_type=fault_type)
        out.append({
            "fault_type": fault_type,
            "n_points": len(player),
            "run_id": player._df["run_id"].iloc[0],
            "service_name": player._df["service_name"].iloc[0],
            "phases": player._df["fault_phase"].value_counts().to_dict(),
        })
    return out


@app.get("/scenarios/m4-demo")
def m4_demo_meta():
    """Métadonnées du scénario pédagogique dédié M4 (seuil dynamique, 7 phases :
    normal -> montée de charge -> charge soutenue -> montée Black Friday -> Black
    Friday soutenu -> spike (au-delà du Black Friday) -> recovery), pour affichage
    avant lancement."""
    player = M4DemoPlayer()
    df = player._df
    return {
        "n_points": len(player),
        "service_name": str(df["service_name"].iloc[0]),
        "metric": "cpu_usage_pct",
        "phases": df["phase"].value_counts().to_dict(),
    }


@app.post("/scenario/upload")
async def upload_scenario(file: UploadFile):
    """Upload d'un run brut réel (sortie directe de collector_final.py, tous les
    services du cluster, non filtré) pour un test aveugle authentique -- la
    plateforme ne reçoit ce fichier que pour le rejouer point par point, jamais pour
    en tirer une info à l'avance. Retourne juste des métadonnées structurelles
    (nombre de points/services), pas le contenu du fichier ni sa vérité terrain."""
    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Seuls les fichiers .csv sont acceptés.")
    content = await file.read()
    try:
        dataset_id = save_uploaded_csv(content)
        # Validation immédiate : instancier un RawRunPlayer vérifie le schéma de colonnes.
        player = RawRunPlayer(dataset_path=uploaded_csv_path(dataset_id))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"CSV invalide : {e}")
    return {
        "dataset_id": dataset_id,
        "n_points": len(player),
        "n_services": player.n_services,
        "filename": file.filename,
    }


# ---------------------------------------------------------------------------
# Ingestion live — le vrai collecteur (collector_final.py) pousse ici ses mesures
# au fil de l'eau depuis le cluster, à la place d'un CSV rejoué après coup.
# ---------------------------------------------------------------------------

@app.post("/ingest/tick")
async def ingest_tick(req: IngestTickRequest, x_ingest_token: str | None = Header(default=None)):
    """Reçoit un batch de mesures fraîchement collectées (une ligne par pod, comme
    un tick de collector_final.py), les fait passer dans le pipeline M1->M2->M3->M4
    en direct, et diffuse les résultats à tous les clients connectés sur /ws/live.
    Ne renvoie jamais les résultats eux-mêmes au collecteur (qui n'en a pas besoin) --
    seulement un accusé de réception, pour ne pas ralentir la boucle de collecte."""
    if INGEST_TOKEN and x_ingest_token != INGEST_TOKEN:
        raise HTTPException(status_code=401, detail="Jeton d'ingestion invalide ou manquant.")
    results = await live_manager.ingest_tick(req.rows)
    return {"ingested": len(results), "received": len(req.rows)}


@app.get("/ingest/stats")
def ingest_stats():
    """État du flux live -- combien de ticks/lignes reçus, combien de clients
    regardent en ce moment, quels services ont déjà été vus. Utile pour vérifier
    que le collecteur pousse bien des données avant même d'ouvrir le Cockpit."""
    return live_manager.stats


@app.get("/ingest/status")
def ingest_status():
    """État ACTUEL du pipeline, un enregistrement plat par service -- endpoint
    dédié à l'intégration Grafana (plugin Infinity), qui interroge en HTTP
    classique par polling plutôt que via /ws/live (WebSocket, pas consommable
    par Infinity). Toujours répondre 200 avec une liste (vide si rien reçu
    encore), jamais d'erreur -- un dashboard SRE ne doit jamais planter juste
    parce que le flux live est calme."""
    return live_manager.current_status()


@app.get("/ingest/timeseries")
def ingest_timeseries(service: str | None = None, limit: int = 500):
    """Historique complet et chronologique du pipeline -- pour de vrais graphiques
    Grafana en courbes (score M1 vs seuil, TTF M3 qui descend vers 0, bande de
    confiance ARIMA de M4), pas juste un instantané. `service` filtre sur un
    service précis (recommandé : une courbe par service lisible, plutôt que
    plusieurs services mélangés sur le même axe temporel)."""
    return live_manager.timeseries(service=service, limit=limit)


@app.websocket("/ws/live")
async def ws_live(websocket: WebSocket):
    """Diffusion en direct des résultats du pipeline live -- pas de play/pause/
    vitesse ici, c'est le cluster réel qui dicte le rythme. À la connexion, le
    client reçoit d'abord un peu d'historique récent pour ne pas arriver sur un
    écran vide s'il se connecte en cours de run.

    Contrairement à /ws/scenario (qui envoie un flux continu pendant un rejeu),
    ce canal peut rester silencieux longtemps si le collecteur ne pousse rien --
    exactement le cas d'usage attendu (attendre un vrai run sur le cluster). Un
    ping léger toutes les 20s évite qu'un composant réseau intermédiaire (load
    balancer, proxy GCP) ne referme la connexion pour inactivité."""
    await websocket.accept()
    live_manager.register(websocket)
    try:
        recent = live_manager.recent_results()
        if recent:
            await _send_json_safe(websocket, {"event": "live_backfill", "data": recent})
        while True:
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=20.0)
            except asyncio.TimeoutError:
                await websocket.send_json({"event": "ping"})
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("Erreur sur /ws/live")
    finally:
        live_manager.unregister(websocket)


# ---------------------------------------------------------------------------
# Endpoints de test indépendant par modèle
# ---------------------------------------------------------------------------

@app.post("/m1/predict")
def m1_predict(req: HistoryRequest):
    """M1 — score d'anomalie LOF sur le dernier point de l'historique fourni."""
    try:
        return m1_anomaly.predict(req.history)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"M1 : {e}")


@app.post("/m2/predict")
def m2_predict(req: HistoryRequest):
    """M2 — classe de panne prédite sur le dernier point de l'historique fourni."""
    try:
        return m2_classification.predict(req.history)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"M2 : {e}")


@app.post("/m3/predict")
def m3_predict(req: HistoryRequest):
    """M3 — temps avant panne (OOM) estimé sur le dernier point de l'historique fourni."""
    try:
        return m3_prediction.predict(req.history)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"M3 : {e}")


@app.post("/m4/predict")
def m4_predict(req: M4Request):
    """M4 — seuil dynamique ARIMA sur une série de valeurs d'une métrique."""
    try:
        return m4_threshold.predict(req.metric_history, metric_name=req.metric_name)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"M4 : {e}")


@app.post("/pipeline/run")
def pipeline_run(req: HistoryRequest):
    """Exécute M1 -> (M2 si anomalie) -> (M3 si OOM plausible) -> M4 sur un historique
    fourni manuellement, hors rejeu de scénario (utile pour tester le pipeline complet
    avec des valeurs saisies à la main devant le jury)."""
    try:
        m1_result = m1_anomaly.predict(req.history)
        m2_result = m2_classification.predict(req.history) if m1_result["smoothed_anomaly"] else None
        m3_result = None
        last_row = req.history[-1]
        if m2_result and m2_result["predicted_class"] == "oom" and last_row.get("mem_limit_mi"):
            try:
                m3_result = m3_prediction.predict(req.history)
            except Exception as e:
                m3_result = {"model": "M3", "error": str(e)}
        cpu_series = [row.get("cpu_usage_pct") for row in req.history if row.get("cpu_usage_pct") is not None]
        m4_result = m4_threshold.predict(cpu_series, metric_name="cpu_usage_pct") if cpu_series else None
        return {"m1": m1_result, "m2": m2_result, "m3": m3_result, "m4": m4_result}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Pipeline : {e}")


# ---------------------------------------------------------------------------
# WebSocket — rejeu de scénario live (cockpit de démo)
# ---------------------------------------------------------------------------

@app.websocket("/ws/scenario")
async def ws_scenario(websocket: WebSocket):
    """
    Protocole (messages JSON envoyés par le client) :
      {"action": "start", "fault_type": "oom", "speed": 5}
      {"action": "start_random", "speed": 5, "blind": true}
      {"action": "start_upload", "dataset_id": "...", "speed": 5}
      {"action": "start_m4_demo", "speed": 5}
      {"action": "pause"}
      {"action": "resume"}
      {"action": "set_speed", "speed": 10}
      {"action": "reveal"}
      {"action": "reset"}

    Messages envoyés par le serveur :
      {"event": "scenario_started", "fault_type": ..., "blind": ..., "raw": ..., "total_steps": ...}
      {"event": "step", "data": {...résultat du pipeline pour ce point...}}
      {"event": "scenario_complete", "blind": ...}
      {"event": "reveal", "fault_type": ..., "run_id": ..., "service_name": ...}
      {"event": "reset_done"}
      {"event": "error", "message": ...}
    """
    await websocket.accept()
    session = ScenarioSession()
    try:
        while True:
            msg = await websocket.receive_json()
            action = msg.get("action")

            if action == "start":
                fault_type = msg.get("fault_type")
                speed = float(msg.get("speed", 5.0))
                blind = bool(msg.get("blind", False))
                if fault_type not in SCENARIOS:
                    await _send_json_safe(websocket, {
                        "event": "error",
                        "message": f"Scénario inconnu : {fault_type}. Options : {list(SCENARIOS)}",
                    })
                    continue
                await session.start(websocket, fault_type, speed, blind=blind)

            elif action == "start_random":
                # Le fault_type est tiré au sort côté serveur (scenario_session.py) --
                # ni le frontend ni la personne qui pilote la démo ne le connaît.
                speed = float(msg.get("speed", 5.0))
                blind = bool(msg.get("blind", True))
                await session.start(websocket, fault_type=None, speed=speed, blind=blind, random_pick=True)

            elif action == "start_upload":
                # Rejeu brut d'un run réel uploadé -- toujours aveugle, tous services.
                dataset_id = msg.get("dataset_id")
                speed = float(msg.get("speed", 5.0))
                try:
                    path = uploaded_csv_path(dataset_id)
                except FileNotFoundError:
                    await _send_json_safe(websocket, {"event": "error", "message": f"Dataset introuvable : {dataset_id}"})
                    continue
                await session.start_raw(websocket, path, speed=speed)

            elif action == "start_m4_demo":
                # Scénario pédagogique dédié M4 (seuil dynamique) -- 4 phases,
                # découplé du pipeline M1->M2->M3->M4 complet.
                speed = float(msg.get("speed", 5.0))
                await session.start_m4_demo(websocket, speed=speed)

            elif action == "reveal":
                truth = session.reveal()
                await _send_json_safe(websocket, {"event": "reveal", **truth})

            elif action == "pause":
                session.pause()
                await _send_json_safe(websocket, {"event": "paused"})

            elif action == "resume":
                session.resume()
                await _send_json_safe(websocket, {"event": "resumed"})

            elif action == "set_speed":
                session.set_speed(float(msg.get("speed", 5.0)))
                await _send_json_safe(websocket, {"event": "speed_set", "speed": session.speed})

            elif action == "reset":
                session.stop()
                await _send_json_safe(websocket, {"event": "reset_done"})

            else:
                await _send_json_safe(websocket, {"event": "error", "message": f"Action inconnue : {action}"})

    except WebSocketDisconnect:
        session.stop()
    except Exception as e:
        logger.exception("Erreur WebSocket")
        session.stop()
