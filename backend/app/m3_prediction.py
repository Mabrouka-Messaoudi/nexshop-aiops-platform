"""
M3 — Prédiction de saturation OOM (Time-To-Failure)

Reproduit le feature engineering de M3_03_FeatureEngineering pour une mesure live, puis
interroge DEUX modèles Gradient Boosting à perte quantile (cf. M3_06_DemoLive_v2) :

  - modèle "point"   (alpha=0.5, médiane) : le chiffre affiché à l'écran (plus robuste
                                             aux valeurs extrêmes que l'ancienne perte quadratique)
  - modèle "safety"  (alpha=0.3, prudent) : sert UNIQUEMENT à décider si on déclenche
                                             l'alerte -- volontairement pessimiste pour ne
                                             pas rater les cas limites (recall alerte@120s
                                             ~0.87 contre ~0.52 pour l'ancien modèle)

Ne s'applique qu'aux services qui meurent par OOM dans le dataset (product-service dans
les données de démo), mais la logique est générique à tout service exposant ces métriques.
"""

from pathlib import Path

import joblib
import pandas as pd

ARTIFACTS_DIR = Path(__file__).parent.parent / "artifacts"

_model_point = joblib.load(ARTIFACTS_DIR / "m3_gb_model_point.joblib")
_model_safety = joblib.load(ARTIFACTS_DIR / "m3_gb_model_safety.joblib")
FEATURE_COLUMNS = joblib.load(ARTIFACTS_DIR / "m3_feature_columns.joblib")

ALERT_THRESHOLD_SEC = 120  # cf. M3_06_DemoLive_v2, validé en LORO CV complet

_TOP_GLOBAL_FEATURES = [
    {"feature": col, "importance": round(float(imp), 4)}
    for col, imp in sorted(zip(FEATURE_COLUMNS, _model_point.feature_importances_), key=lambda kv: kv[1], reverse=True)[:6]
]


def _parse_mi(value) -> float:
    """Convertit '300Mi' -> 300.0 (chaîne dans les CSV bruts, parfois déjà numérique en live)."""
    if isinstance(value, str):
        return float(value.replace("Mi", "").strip())
    return float(value)


def _build_features(buffer_rows: list[dict]) -> pd.Series:
    df = pd.DataFrame(buffer_rows).copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values("timestamp").reset_index(drop=True)

    # M3 a été entraîné EXCLUSIVEMENT sur des lignes fault_phase == "during_fault"
    # (cf. m3_cleaning.py cellule 10 : `during = df[df['fault_phase']=='during_fault']`,
    # utilisé pour TOUT le feature engineering en aval, y compris elapsed_since_start_sec
    # qui est explicitement documenté comme "temps écoulé depuis le début de l'épisode
    # during_fault"). En live, le buffer partagé avec M1/M2 contient aussi les minutes
    # de pre_fault (le collecteur les envoie avant le patch mémoire) -- on les exclut
    # ici pour rester fidèle à la distribution d'entraînement : sans ce filtre,
    # elapsed_since_start_sec serait gonflé du temps de pre_fault, un vrai décalage
    # par rapport à ce que le modèle a appris.
    if "fault_phase" in df.columns and df["fault_phase"].notna().any():
        df = df[df["fault_phase"] == "during_fault"].reset_index(drop=True)

    if df.empty:
        raise ValueError(
            "Aucun point 'during_fault' dans l'historique fourni -- M3 ne s'applique "
            "qu'une fois la fenêtre de panne commencée (avant ça, rien à prédire)."
        )

    df["mem_limit_mi"] = df["mem_limit_mi"].apply(_parse_mi)
    df["mem_request_mi"] = df["mem_request_mi"].apply(_parse_mi)

    df["delta_t_sec"] = df["timestamp"].diff().dt.total_seconds()
    df["elapsed_since_start_sec"] = (df["timestamp"] - df["timestamp"].iloc[0]).dt.total_seconds()

    def rate(col):
        return df[col].diff() / df["delta_t_sec"]

    df["memory_usage_pct_rate"] = rate("memory_usage_pct")
    df["cpu_usage_pct_rate"] = rate("cpu_usage_pct")
    df["jvm_heap_used_pct_rate"] = rate("jvm_heap_used_pct")
    df["gc_pause_rate"] = rate("gc_pause_total_sec")
    df["log_error_rate"] = rate("log_error_count")
    df["log_warn_rate"] = rate("log_warn_count")

    df["memory_usage_pct_roll3"] = df["memory_usage_pct"].rolling(3, min_periods=1).mean()

    df["mem_headroom_pct"] = 100 - df["memory_usage_pct"]
    df["mem_headroom_mi"] = df["mem_limit_mi"] * df["mem_headroom_pct"] / 100
    df["mem_request_to_limit_ratio"] = df["mem_request_mi"] / df["mem_limit_mi"]

    df["restart_count_cumulative"] = df["restart_count_delta"].fillna(0).cumsum()

    last = df.iloc[-1].copy()

    # One-hot manuel pour la dernière ligne (les catégories sont figées, cf. feature_columns)
    row = last.to_dict()
    for col, value in [("node_name", last.get("node_name")),
                        ("last_terminated_reason", last.get("last_terminated_reason", "none")),
                        ("exception_signature", last.get("exception_signature", "none"))]:
        for feat_col in FEATURE_COLUMNS:
            if feat_col.startswith(f"{col}_"):
                cat = feat_col[len(col) + 1:]
                row[feat_col] = int(value == cat)

    series = pd.Series(row).reindex(FEATURE_COLUMNS).astype(float).fillna(0)
    # rates/deltas indéfinis sur le tout premier point du buffer -> 0 (pas encore de variation observée)
    return series.fillna(0)


def predict(buffer_rows: list[dict]) -> dict:
    features = _build_features(buffer_rows)
    X = features.to_frame().T

    ttf_point = float(_model_point.predict(X)[0])
    ttf_safety = float(_model_safety.predict(X)[0])
    alert = ttf_safety < ALERT_THRESHOLD_SEC

    return {
        "model": "M3",
        "time_to_failure_display_sec": round(ttf_point, 1),
        "time_to_failure_safety_sec": round(ttf_safety, 1),
        "alert_threshold_sec": ALERT_THRESHOLD_SEC,
        "alert": bool(alert),
        "top_features": _TOP_GLOBAL_FEATURES,
    }
