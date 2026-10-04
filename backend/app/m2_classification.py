"""
M2 — Classification de panne (Gradient Boosting, 5 classes)

Contrairement à M1/M3, le code de cleaning et de feature engineering de M2 était déjà
écrit sous forme de fonctions fit/apply réutilisables (cleaning_pipeline.py,
feature_engineering.py) -- on les réutilise ici telles quelles, sans les récrire,
exactement comme prévu par leur documentation ("rejouable en démo live").

Classes : none, oom, cpu_throttle, crashloop, db_down
"""

import json
from pathlib import Path

import joblib
import pandas as pd

from .m2_cleaning_pipeline_src import apply_cleaning
from .m2_feature_engineering_src import build_window_features

ARTIFACTS_DIR = Path(__file__).parent.parent / "artifacts"

_model = joblib.load(ARTIFACTS_DIR / "m2_model.pkl")  # sklearn Pipeline (scaler + GradientBoostingClassifier)
_feature_columns = json.load(open(ARTIFACTS_DIR / "m2_feature_columns.json"))
_cleaning_stats = json.load(open(ARTIFACTS_DIR / "m2_cleaning_stats.json"))

CLASSES = list(_model.classes_)  # ['cpu_throttle', 'crashloop', 'db_down', 'none', 'oom']

# Importance globale (pas par instance -- GradientBoosting ne donne pas nativement une
# explication par prédiction sans SHAP ; ceci répond à "sur quoi le modèle s'appuie le
# plus en général", calculé une fois au chargement, pas recalculé à chaque appel.
_clf = _model.named_steps.get("clf", _model.steps[-1][1])
_TOP_GLOBAL_FEATURES = [
    {"feature": col, "importance": round(float(imp), 4)}
    for col, imp in sorted(zip(_feature_columns, _clf.feature_importances_), key=lambda kv: kv[1], reverse=True)[:6]
]


def predict(buffer_rows: list[dict]) -> dict:
    """buffer_rows : historique brut du service (run_id, service_name, timestamp, métriques...)."""
    df = pd.DataFrame(buffer_rows)

    df_clean = apply_cleaning(df, _cleaning_stats)
    df_feat = build_window_features(df_clean)

    last_row = df_feat.iloc[[-1]]
    X = last_row.reindex(columns=_feature_columns, fill_value=0)
    # Filet de sécurité : cleaning_stats a été figé sur le train (services tracés),
    # certains services du cluster complet (ex. sans tracing) produisent des NaN
    # structurels que ces stats ne couvrent pas (ex. trace_error_span_ratio). 0 encode
    # ici "signal non disponible", cohérent avec la convention déjà utilisée ailleurs.
    X = X.fillna(0)

    proba = _model.predict_proba(X)[0]
    pred_class = CLASSES[int(proba.argmax())]

    return {
        "model": "M2",
        "predicted_class": pred_class,
        "confidence": round(float(proba.max()), 4),
        "probabilities": {cls: round(float(p), 4) for cls, p in zip(CLASSES, proba)},
        "top_features": _TOP_GLOBAL_FEATURES,
    }
