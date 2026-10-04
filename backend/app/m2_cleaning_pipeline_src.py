#!/usr/bin/env python3
"""
Pipeline de cleaning fit/apply pour le dataset multi-pannes NexShop.

Principe : toutes les statistiques nécessaires au nettoyage (médianes
d'imputation, catégories connues pour le one-hot encoding) sont calculées
UNE SEULE FOIS sur le train (fit_cleaning), puis sauvegardées dans
cleaning_stats.json. Le test et les futures données live de démo réutilisent
ces mêmes statistiques figées (apply_cleaning) -- jamais recalculées à la
volée sur un petit échantillon frais, ce qui garantirait une imputation
instable et incohérente avec ce que le modèle a appris.

Usage:
    python3 cleaning_pipeline.py
    (fit sur nexshop_dataset_train_raw.csv, apply sur train + test)
"""

import json
import pandas as pd

IMPUTE_ZERO = [
    "db_active_connections_mongo",
    "db_query_duration_avg_ms",
    "db_query_duration_max_ms",
    "restart_count_delta",
]

IMPUTE_MEDIAN = [
    "memory_usage_pct",
    "jvm_heap_used_pct",
    "memory_working_set_bytes",
    "node_load1",
    "node_cpu_usage_pct",
    "node_memory_available_pct",
    "cpu_usage_pct",
    "gc_pause_total_sec",
    "http_p95_latency_ms",
]

CONSTANT_COLS = ["profile", "waiting_reason"]

ONEHOT_COLS = ["exception_signature", "last_terminated_reason"]

METADATA_NO_IMPUTE = ["node_name"]

STATS_FILE = "model/cleaning_stats.json"


def fit_cleaning(df: pd.DataFrame) -> dict:
    """Calcule les statistiques de cleaning à partir du TRAIN uniquement."""
    stats = {}

    stats["impute_zero_cols"] = IMPUTE_ZERO
    stats["impute_median"] = {c: float(df[c].median()) for c in IMPUTE_MEDIAN}
    stats["constant_cols"] = CONSTANT_COLS
    stats["onehot_cols"] = ONEHOT_COLS
    # Catégories connues au moment du fit -- figées, pour que apply_cleaning
    # produise TOUJOURS les mêmes colonnes one-hot, même si le test ou les
    # données live ne contiennent pas toutes les catégories (ou en montrent
    # une jamais vue, qui sera alors ignorée plutôt que de créer une colonne
    # surprise que le modèle n'a jamais vue à l'entraînement).
    stats["onehot_categories"] = {c: sorted(df[c].dropna().unique().tolist()) for c in ONEHOT_COLS}
    stats["metadata_no_impute"] = METADATA_NO_IMPUTE

    return stats


def apply_cleaning(df: pd.DataFrame, stats: dict) -> pd.DataFrame:
    """Applique le cleaning à un dataframe (train, test, ou données live),
    en utilisant exclusivement les statistiques déjà calculées (stats)."""
    df = df.copy()

    # 1. Imputation à 0
    for c in stats["impute_zero_cols"]:
        if c in df.columns:
            df[c] = df[c].fillna(0)

    # 2. Imputation à la médiane (valeur du TRAIN, jamais recalculée ici)
    for c, med in stats["impute_median"].items():
        if c in df.columns:
            df[c] = df[c].fillna(med)

    # 3. Suppression des colonnes constantes
    df = df.drop(columns=[c for c in stats["constant_cols"] if c in df.columns])

    # 4. One-hot encoding avec catégories figées (fit sur train)
    for c in stats["onehot_cols"]:
        if c not in df.columns:
            continue
        known_cats = stats["onehot_categories"][c]
        for cat in known_cats:
            df[f"{c}_{cat}"] = (df[c] == cat)
        # Catégorie inconnue (jamais vue au fit) : signalée mais pas encodée
        # dans une colonne surprise -- reste simplement à False sur toutes
        # les colonnes one-hot existantes, ce qui est le comportement correct
        # par défaut (le modèle ne peut pas exploiter une catégorie inédite).
        unknown = set(df[c].dropna().unique()) - set(known_cats)
        if unknown:
            print(f"⚠️  Catégories inédites pour {c} (non vues au fit) : {unknown}")
        df = df.drop(columns=[c])

    return df


def main():
    train_raw = pd.read_csv("data/nexshop_dataset_train_raw.csv")
    test_raw = pd.read_csv("data/nexshop_dataset_test_raw.csv")

    print("--- Fit du cleaning sur le train uniquement ---")
    stats = fit_cleaning(train_raw)
    with open(STATS_FILE, "w") as f:
        json.dump(stats, f, indent=2)
    print(f"Statistiques sauvegardées -> {STATS_FILE}")
    print(json.dumps(stats, indent=2, ensure_ascii=False))

    print("\n--- Application au train ---")
    train_clean = apply_cleaning(train_raw, stats)
    train_clean.to_csv("data/nexshop_dataset_train_clean.csv", index=False)
    print(f"Shape train_clean : {train_clean.shape}")

    print("\n--- Application au test (mêmes statistiques, aucun recalcul) ---")
    test_clean = apply_cleaning(test_raw, stats)
    test_clean.to_csv("data/nexshop_dataset_test_clean.csv", index=False)
    print(f"Shape test_clean : {test_clean.shape}")

    # Vérification : mêmes colonnes des deux côtés (indispensable pour le modèle)
    same_cols = list(train_clean.columns) == list(test_clean.columns)
    print(f"\nColonnes identiques train/test : {same_cols}")
    if not same_cols:
        print("Train :", train_clean.columns.tolist())
        print("Test  :", test_clean.columns.tolist())


if __name__ == "__main__":
    main()