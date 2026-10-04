#!/usr/bin/env python3
"""
Feature engineering par fenêtre glissante pour le dataset multi-pannes NexShop.

Principe : pour chaque (run_id, service_name), on trie par timestamp et on
calcule, sur une fenêtre des N derniers points, 3 statistiques par métrique de
base :
  - rolling_mean : lissage de la tendance récente
  - rolling_std  : détecte l'oscillation (plat pour cpu_throttle, pic isolé
                   pour oom, oscillant pour crashloop -- signatures déjà
                   identifiées dans les notebooks individuels)
  - diff_1       : pente instantanée (différence avec le point précédent)

Ces mêmes calculs sont rejouables en démo live : l'application maintient un
buffer des N dernières mesures par service, et applique EXACTEMENT la même
fonction (build_window_features) sur ce buffer avant d'appeler le modèle --
aucune divergence de logique entre entraînement et démo.

Usage: python3 feature_engineering.py
A lancer après cleaning_pipeline.py (opère sur les CSV déjà nettoyés).
"""

import pandas as pd

WINDOW = 5

BASE_METRICS = [
    "restart_count_delta",
    "cpu_usage_pct",
    "memory_usage_pct",
    "http_p95_latency_ms",
    "log_error_count",
    "node_memory_available_pct",
]


def build_window_features(df: pd.DataFrame, window: int = WINDOW) -> pd.DataFrame:
    """Calcule les features de fenêtre glissante sur un dataframe déjà nettoyé.

    df doit contenir : run_id, service_name, timestamp, et les BASE_METRICS.
    Rejouable à l'identique sur train, test, ou un buffer live de démo (dans
    ce dernier cas, run_id/service_name peuvent être des valeurs fixes -- un
    seul "run" en cours -- tant que le buffer est trié chronologiquement).
    """
    df = df.sort_values(["run_id", "service_name", "timestamp"]).copy()
    grouped = df.groupby(["run_id", "service_name"], sort=False)

    for metric in BASE_METRICS:
        df[f"{metric}_roll_mean"] = (
            grouped[metric].transform(lambda s: s.rolling(window, min_periods=1).mean())
        )
        df[f"{metric}_roll_std"] = (
            grouped[metric].transform(lambda s: s.rolling(window, min_periods=1).std())
        )
        df[f"{metric}_diff1"] = grouped[metric].transform(lambda s: s.diff())

    # rolling_std sur un seul point (début de séquence) et diff1 sur le tout
    # premier point d'un run sont NaN par construction (pas d'historique
    # disponible) -- imputés à 0 : "pas encore de variation observée" est une
    # vraie valeur ici, pas un trou de collecte comme dans le cleaning
    # précédent, donc pas besoin de statistique de train à sauvegarder.
    new_cols = [c for c in df.columns if c.endswith(("_roll_mean", "_roll_std", "_diff1"))]
    df[new_cols] = df[new_cols].fillna(0)

    return df


def main():
    train = pd.read_csv("data/nexshop_dataset_train_clean.csv")
    test = pd.read_csv("data/nexshop_dataset_test_clean.csv")

    print(f"Fenêtre glissante : {WINDOW} points, groupé par (run_id, service_name)")
    print(f"Métriques de base : {BASE_METRICS}")
    print(f"-> {len(BASE_METRICS)} x 3 = {len(BASE_METRICS) * 3} nouvelles colonnes")

    train_feat = build_window_features(train)
    test_feat = build_window_features(test)

    train_feat.to_csv("data/nexshop_dataset_train_features.csv", index=False)
    test_feat.to_csv("data/nexshop_dataset_test_features.csv", index=False)

    print(f"\n✅ Train -> nexshop_dataset_train_features.csv : {train_feat.shape}")
    print(f"✅ Test  -> nexshop_dataset_test_features.csv  : {test_feat.shape}")

    same_cols = list(train_feat.columns) == list(test_feat.columns)
    print(f"\nColonnes identiques train/test : {same_cols}")

    # Aperçu rapide : est-ce que le signal attendu apparaît bien (ex.
    # restart_count_delta_roll_std plus élevé pour crashloop que cpu_throttle) ?
    print("\nAperçu -- moyenne de restart_count_delta_roll_std par label (train) :")
    print(train_feat.groupby("label")["restart_count_delta_roll_std"].mean().round(3))


if __name__ == "__main__":
    main()