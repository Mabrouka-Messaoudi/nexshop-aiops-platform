"""
M1 — Détection d'anomalie (LOF)

Reproduit fidèlement, pour une mesure live, le pipeline construit dans les notebooks
03_cleaning -> 04_feature_engineering -> 05_modeling -> 06_evaluation_v2 :

  1. Extraction du type de service depuis le nom de pod (stable au redéploiement)
  2. Encodage one-hot de exception_signature
  3. Rolling mean/std (window=5) + delta sur 20 métriques de base, groupé par service
  4. Réconciliation de schéma (exclusion des 3 métriques indisponibles côté pannes)
  5. Standardisation (scaler figé, entraîné sur trafic normal uniquement)
  6. Score LOF (modèle retenu en éval : LOF > Isolation Forest) + seuil P99 du train
  7. Filtre de confiance (metrics_missing_ratio > 30% -> prédiction écartée AVANT lissage)
  8. Lissage temporel / hystérésis (fenêtre=3, vote majoritaire) -> ce qui a fait passer
     le rappel db_down de 88% à 99% dans l'évaluation.

Le modèle n'a jamais vu le dataset de pannes pendant l'entraînement (100% trafic normal) :
c'est un modèle de détection non supervisée, pas un classifieur.

LIMITE CONNUE (honnête, pas cachée) : le notebook d'évaluation calcule le lissage avec
`rolling(window=3, center=True)` -- une fenêtre CENTRÉE qui utilise le point SUIVANT
(t+1) en plus des deux précédents. C'est structurellement impossible en vrai temps réel
(on ne connaît pas encore t+1 au moment de décider pour t). Ce module utilise donc une
fenêtre glissante ARRIÈRE uniquement (t-2, t-1, t) -- la seule option honnête en live,
mais dont la performance exacte n'a jamais été mesurée séparément de la version centrée
validée en évaluation. Les gains de rappel cités ci-dessus (db_down 88%->99%) ont été
mesurés avec la fenêtre centrée -- probablement une bonne approximation de ce qu'obtient
la fenêtre arrière, mais pas rigoureusement identique.
"""

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

ARTIFACTS_DIR = Path(__file__).parent.parent / "artifacts"

# ---- Chargement des artefacts (une seule fois, au démarrage du service) ----
_lof = joblib.load(ARTIFACTS_DIR / "m1_lof.joblib")
_scaler = joblib.load(ARTIFACTS_DIR / "m1_scaler.joblib")
_modeling_meta = json.load(open(ARTIFACTS_DIR / "m1_modeling_metadata.json"))
_eval_report = json.load(open(ARTIFACTS_DIR / "m1_evaluation_report_v2.json"))
_cleaning_stats = json.load(open(ARTIFACTS_DIR / "m1_cleaning_stats.json"))

FINAL_FEATURE_COLUMNS = _modeling_meta["final_feature_columns"]
KNOWN_SERVICE_TYPES = sorted(_modeling_meta["known_service_types"], key=len, reverse=True)
THRESHOLD = _eval_report["chosen_threshold"]  # score LOF au 99e percentile du train (trafic normal)

BASE_METRICS = [
    "cpu_usage_pct", "memory_usage_pct", "memory_working_set_bytes", "restart_count_delta",
    "jvm_heap_used_pct", "gc_pause_total_sec", "http_p95_latency_ms",
    "db_active_connections_mongo", "db_query_duration_avg_ms", "db_query_duration_max_ms",
    "node_cpu_usage_pct", "node_load1", "node_memory_available_pct",
    "log_error_count", "log_warn_count", "log_volume_total", "trace_error_span_ratio",
]  # les 17 métriques encore utilisées après réconciliation de schéma (étape 5.2)

WINDOW = 5
STRUCTURAL_COLS = [c for c in _cleaning_stats["structural_columns"] if c in BASE_METRICS]

# NB : cleaning_stats["service_medians"] est indexé par NOM DE POD EXACT du train
# (ex. "product-service-8f55f5779-s9vpt"), pas par type de service -- inutilisable tel
# quel en live où les pods ont d'autres suffixes à chaque redéploiement. On utilise à la
# place une disponibilité empirique par TYPE de service (dérivée une fois du dataset brut
# de train, cf. m1_structural_availability_by_service_type.json), et une médiane globale
# (toutes les valeurs connues du train, tous services confondus) comme repli d'imputation.
_structural_availability = json.load(open(ARTIFACTS_DIR / "m1_structural_availability_by_service_type.json"))
_GLOBAL_MEDIAN_FALLBACK = {col: 0.0 for col in BASE_METRICS}  # 0 = comportement figé du cleaning notebook (3.5)

# Médianes par type de service (calculées sur train_clean, cf. 06_evaluation_v2 cellule 7 :
# `service_type_medians = train_clean.groupby("service_type")[base_metrics_remaining].median()`)
# -- utilisées pour imputer une valeur PONCTUELLEMENT manquante (scrape raté), à ne pas
# confondre avec les flags is_applicable ci-dessus (métrique qui n'existe STRUCTURELLEMENT
# jamais pour ce type de service). 0 reste le repli si jamais le type de service est inconnu
# de ce fichier (aucun cas de ce genre trouvé sur le train actuel, mais le repli existe pour
# rester robuste à un futur type de service qui apparaîtrait sans historique).
_service_type_medians = json.load(open(ARTIFACTS_DIR / "m1_service_type_medians.json"))

# Hystérésis (identique à l'évaluation, 6.16) : fenêtre 3, "max" par défaut,
# vote majoritaire pour oom/crashloop où la vérité terrain corrigée est fiable.
SMOOTH_WINDOW = 3
V2_FAULT_TYPES = {"oom", "crashloop"}  # utilisé uniquement pour piloter la politique de lissage, pas pour tricher

# Filtre de confiance (identique à 06_evaluation_v2 cellule 8/9 : `low_confidence =
# metrics_missing_ratio > 0.3` -- appliqué AVANT le lissage, pas après). Manquait en
# production jusqu'ici (seul le lissage était reproduit, pas ce filtre en amont).
CONFIDENCE_THRESHOLD = 0.3


def extract_service_type(pod_name: str) -> str:
    for prefix in KNOWN_SERVICE_TYPES:
        if pod_name.startswith(prefix + "-"):
            return prefix
    return "unknown"


def _build_features(buffer_rows: list[dict]) -> tuple[pd.Series, float]:
    """Reproduit 04_feature_engineering sur le buffer, retourne (features, metrics_missing_ratio)
    de la dernière ligne. Le ratio est calculé AVANT imputation (comme en éval, cellule 7 :
    `raw["metrics_missing_ratio"] = raw[base_metrics_remaining].isna().mean(axis=1)`),
    sinon il vaudrait toujours 0 après coup et le filtre de confiance ne servirait à rien."""
    df = pd.DataFrame(buffer_rows)
    service_name = df["service_name"].iloc[-1]
    service_type = extract_service_type(service_name)

    for col in BASE_METRICS:
        if col not in df.columns:
            df[col] = None

    # Ratio de métriques manquantes sur la dernière ligne, AVANT toute imputation --
    # c'est ce ratio-là (pas un après-imputation qui serait toujours 0) qui alimente
    # le filtre de confiance dans predict().
    last_raw = df[BASE_METRICS].iloc[-1]
    metrics_missing_ratio = float(last_raw.isna().mean())

    # Imputation d'une valeur PONCTUELLEMENT manquante (scrape raté) : médiane du train
    # pour ce type de service -- même méthode que 06_evaluation_v2 cellule 7. 0 seulement
    # si ce type de service n'a aucune médiane connue (cas non observé sur le train actuel).
    type_medians = _service_type_medians.get(service_type, {})
    for col in BASE_METRICS:
        if df[col].isna().any():
            df[col] = df[col].fillna(type_medians.get(col, 0.0))

    # Rolling mean/std + delta (identique à 04_feature_engineering)
    for col in BASE_METRICS:
        df[f"{col}_roll_mean5"] = df[col].rolling(window=WINDOW, min_periods=1).mean()
        df[f"{col}_roll_std5"] = df[col].rolling(window=WINDOW, min_periods=1).std().fillna(0)
        df[f"{col}_delta"] = df[col].diff().fillna(0)

    # Flags de disponibilité (constants par type de service, cf. 03_cleaning 3.6)
    type_availability = _structural_availability.get(service_type, {})
    for col in STRUCTURAL_COLS:
        df[f"{col}_is_applicable"] = int(type_availability.get(col, 0))

    # One-hot exception_signature (catégorie 'none' implicite)
    exc = df.get("exception_signature", pd.Series(["none"] * len(df)))
    for cat in ["client_error", "connection_lost", "session_expired", "kafka_coordination_error"]:
        df[f"exc_{cat}"] = (exc == cat).astype(int)

    # One-hot type de service
    for svc in KNOWN_SERVICE_TYPES:
        df[f"svc_{svc}"] = int(service_type == svc)

    last_row = df.iloc[-1]
    features = last_row.reindex(FINAL_FEATURE_COLUMNS).fillna(0).astype(float)
    return features, metrics_missing_ratio


def predict(buffer_rows: list[dict], recent_predictions: list[int] | None = None, fault_type_hint: str | None = None) -> dict:
    """
    buffer_rows : historique brut du service (>= 1 point, idéalement >= 5 pour features stables)
    recent_predictions : les décisions FILTRÉES (post-confiance, pré-lissage) des 1-2 derniers
                          points de CE service, à passer au prochain appel pour le lissage.
    fault_type_hint : uniquement pour choisir la politique de lissage v1/v2 en démo pédagogique
                       (en prod réelle, inconnu à l'avance -> on utilise v1 "max" par défaut).
    """
    features, metrics_missing_ratio = _build_features(buffer_rows)
    X = features.to_frame().T
    X_scaled = _scaler.transform(X)[0]

    anomaly_score = float(-_lof.decision_function(X_scaled.reshape(1, -1))[0])
    raw_pred = int(anomaly_score >= THRESHOLD)

    # Filtre de confiance (06_evaluation_v2, AVANT le lissage) : une prédiction sur un
    # point où plus de 30% des métriques de base manquaient est écartée -- traitée comme
    # "pas d'alerte" pour cette lecture précise, plutôt que de fausser le vote suivant
    # avec un signal peu fiable.
    low_confidence = metrics_missing_ratio > CONFIDENCE_THRESHOLD
    filtered_pred = raw_pred if not low_confidence else 0

    # Lissage temporel : fenêtre glissante ARRIÈRE (t-2, t-1, t) -- PAS centrée, contrairement
    # au notebook d'évaluation (cf. limite documentée en tête de fichier). C'est la seule
    # option honnête en direct : impossible de connaître t+1 au moment de décider pour t.
    window_preds = (recent_predictions or [])[-(SMOOTH_WINDOW - 1):] + [filtered_pred]
    if fault_type_hint in V2_FAULT_TYPES:
        smoothed_pred = int((sum(window_preds) / len(window_preds)) >= 0.5)  # vote majoritaire
    else:
        smoothed_pred = int(max(window_preds))  # max (v1)

    # Explicabilité par instance : les features les plus "hors norme" (plus grand |z-score|
    # après standardisation) pour CETTE mesure précise -- pas une importance globale figée,
    # une vraie réponse à "pourquoi CE point a été jugé anormal".
    z_scores = list(zip(FINAL_FEATURE_COLUMNS, X_scaled.tolist()))
    top_features = sorted(z_scores, key=lambda kv: abs(kv[1]), reverse=True)[:5]
    top_features = [{"feature": k, "z_score": round(v, 2)} for k, v in top_features]

    return {
        "model": "M1",
        "anomaly_score": round(anomaly_score, 4),
        "threshold": round(THRESHOLD, 4),
        "raw_anomaly": bool(raw_pred),
        "metrics_missing_ratio": round(metrics_missing_ratio, 3),
        "low_confidence": bool(low_confidence),
        "filtered_anomaly": bool(filtered_pred),  # ce qui doit nourrir l'historique de lissage, pas raw_anomaly
        "smoothed_anomaly": bool(smoothed_pred),
        "confidence": round(min(anomaly_score / THRESHOLD, 3.0), 2) if THRESHOLD else None,
        "top_features": top_features,
    }
