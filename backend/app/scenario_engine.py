"""
Scenario Engine — rejeu de données de panne réelles pour la démo jury.

Deux modes :

1. ScenarioPlayer — scénarios CURÉS (backend/data/scenario_*.csv), pré-filtrés sur le
   service cible, pour une démo pédagogique claire (Cockpit, boutons de panne nommés).

2. RawRunPlayer — rejeu BRUT d'un run complet uploadé (tous les services du cluster,
   dans l'ordre exact de collecte, non filtré). C'est le mode "test réel" : la
   plateforme reçoit les mêmes données qu'un vrai collector_final.py enverrait, sans
   savoir à l'avance quel service est affecté. Utilisé pour le mode aveugle strict.

Principe d'honnêteté du pipeline (les deux modes le respectent) :
  - Le lissage temporel de M1 ne dépend JAMAIS du fault_type réel : en mode aveugle
    (blind=True) ou en rejeu brut, `fault_type_hint=None` est passé à M1, qui retombe
    sur la politique par défaut (max, la plus prudente). Seul le mode démo pédagogique
    non-aveugle (blind=False) utilise le fault_type choisi par l'utilisateur pour
    illustrer la politique v1/v2 documentée dans l'évaluation -- jamais pour "aider"
    le modèle à deviner.
  - M3 ne se déclenche jamais sur un oracle "on sait que c'est de l'OOM" : il se
    déclenche uniquement si M2 (qui ne voit que les features) a lui-même classifié
    le point comme "oom". C'est la cascade de décision réelle, pas une triche interne.
"""

import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

import pandas as pd

from . import m1_anomaly, m2_classification, m3_prediction, m4_threshold
from .buffers import ServiceBufferStore

DATA_DIR = Path(__file__).parent.parent / "data"
UPLOADS_DIR = DATA_DIR / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)

SCENARIOS = {
    "cpu_throttle": "scenario_cpu_throttle.csv",
    "crashloop": "scenario_crashloop.csv",
    "db_down": "scenario_db_down.csv",
    "oom": "scenario_oom.csv",
}

REQUIRED_RAW_COLUMNS = {
    "run_id", "service_name", "timestamp",
    "cpu_usage_pct", "memory_usage_pct", "restart_count_delta",
    "http_p95_latency_ms", "log_error_count", "node_memory_available_pct",
}

# Seuil du garde-fou mémoire (voir _execute_pipeline_step) -- 90% de la limite
# configurée du conteneur. Choisi empiriquement sur le run réel qui a motivé ce
# correctif : la vraie casse a eu lieu à ~97% du plafond, et M2 avait déjà perdu
# confiance dès ~85%. 90% laisse une marge de détection avant le point de rupture
# tout en évitant de déclencher le garde-fou trop tôt sur une charge normale.
CRITICAL_MEMORY_RATIO_THRESHOLD = 0.90


def _execute_pipeline_step(
    row: dict,
    step_index: int,
    buffers: ServiceBufferStore,
    m1_history: dict,
    m4_history: dict,
    blind: bool,
    fault_type_for_smoothing: str | None,
) -> dict:
    """Logique de pipeline PARTAGÉE entre scénarios curés et rejeu brut. Une seule
    version du pipeline, pour être certain que le mode "démo pédagogique" et le mode
    "test aveugle réel" se comportent exactement pareil du point de vue des modèles."""
    run_id, service = row["run_id"], row["service_name"]
    key = (run_id, service)

    buffer_rows = buffers.push(run_id, service, row)

    # --- M1 : détection d'anomalie ---
    # fault_type_for_smoothing est None dès que blind=True (imposé par l'appelant) :
    # la politique de lissage ne peut jamais dépendre d'une vérité que M1 n'a pas.
    m1_result = m1_anomaly.predict(
        buffer_rows,
        recent_predictions=m1_history.get(key, []),
        fault_type_hint=fault_type_for_smoothing,
    )
    # L'historique de lissage doit contenir la prédiction FILTRÉE (post-confiance), pas
    # la brute -- cf. 06_evaluation_v2 : le rolling s'applique sur pred_filtered, pas sur
    # pred. Utiliser raw_anomaly ici ferait entrer dans le vote des points explicitement
    # jugés peu fiables (metrics_missing_ratio > 30%).
    m1_history.setdefault(key, []).append(int(m1_result["filtered_anomaly"]))

    # --- M2 : classification (seulement si M1 a détecté quelque chose, comme en prod) ---
    m2_result = None
    if m1_result["smoothed_anomaly"]:
        m2_result = m2_classification.predict(buffer_rows)

        # Garde-fou sur le niveau ABSOLU de mémoire -- vécu en pratique (rejeu du CSV
        # réel d'un run OOM) : dans la dernière ligne droite avant un vrai crash, la
        # mémoire continue de grimper sans jamais redescendre, mais son TAUX de
        # croissance ralentit (elle plafonne près de la limite) -- et M2, dont les
        # features captent surtout la vitesse de dégradation, perd alors confiance et
        # peut basculer vers "cpu_throttle"/"none" alors que le système est plus
        # proche que jamais de la casse. Ce garde-fou n'écrase JAMAIS la prédiction
        # réelle du modèle (transparence : on montre ce qu'il a vraiment dit), il
        # ajoute juste un signal supplémentaire basé sur le niveau brut, indépendant
        # de ce que le modèle a appris.
        mem_limit_mi = row.get("mem_limit_mi")
        mem_bytes = row.get("memory_working_set_bytes")
        critical_ratio = None
        if mem_limit_mi not in (None, "") and mem_bytes not in (None, "") and pd.notna(mem_limit_mi) and pd.notna(mem_bytes):
            try:
                # mem_limit_mi arrive au format Kubernetes ("250Mi"), pas un nombre nu --
                # vécu en pratique : un float("250Mi") direct lève silencieusement une
                # exception avalée par le except ci-dessous, laissant le ratio à None
                # sans jamais prévenir que le garde-fou ne se déclenche jamais.
                mem_limit_str = str(mem_limit_mi).strip()
                mem_limit_num = float(mem_limit_str[:-2]) if mem_limit_str.endswith("Mi") else float(mem_limit_str)
                critical_ratio = float(mem_bytes) / (mem_limit_num * 1024 * 1024)
            except (TypeError, ValueError, ZeroDivisionError):
                critical_ratio = None
        m2_result["critical_memory_ratio"] = round(critical_ratio, 3) if critical_ratio is not None else None
        m2_result["critical_memory_safety_net"] = bool(critical_ratio is not None and critical_ratio >= CRITICAL_MEMORY_RATIO_THRESHOLD)

    # --- M3 : prédiction TTF -- déclenché par la décision de M2, OU par le garde-fou
    # mémoire ci-dessus si M2 a perdu confiance juste avant un vrai crash (sinon M3
    # se tairait exactement quand son avertissement compte le plus).
    m3_result = None
    if (
        m2_result
        and (m2_result["predicted_class"] == "oom" or m2_result.get("critical_memory_safety_net"))
        and row.get("mem_limit_mi") not in (None, "")
        and pd.notna(row.get("mem_limit_mi"))
    ):
        try:
            m3_result = m3_prediction.predict(buffer_rows)
        except Exception as e:
            m3_result = {"model": "M3", "error": str(e)}

    # --- M4 : seuil dynamique sur cpu_usage_pct ---
    cpu_hist = m4_history.setdefault(key, [])
    cpu_hist.append(row["cpu_usage_pct"])
    m4_result = m4_threshold.predict(cpu_hist, metric_name="cpu_usage_pct")

    result = {
        "step": step_index,
        "timestamp": str(row["timestamp"]),
        "run_id": run_id,
        "service_name": service,
        "ground_truth_label": row.get("label", row.get("fault_type")),
        "ground_truth_phase": row.get("fault_phase"),
        "m1": m1_result,
        "m2": m2_result,
        "m3": m3_result,
        "m4": m4_result,
    }
    if blind:
        result = {k: v for k, v in result.items() if k not in ("ground_truth_label", "ground_truth_phase")}
    return result


@dataclass
class ScenarioPlayer:
    """Scénario curé : un seul service, choisi à l'avance pour raconter une histoire
    pédagogique claire (cf. backend/data/scenario_*.csv)."""

    fault_type: str
    speed: float = 1.0
    blind: bool = False
    _df: pd.DataFrame = field(init=False, repr=False)
    _buffers: ServiceBufferStore = field(default_factory=ServiceBufferStore, init=False)
    _m1_history: dict = field(default_factory=dict, init=False)
    _m4_history: dict = field(default_factory=dict, init=False)

    def __post_init__(self):
        if self.fault_type not in SCENARIOS:
            raise ValueError(f"Scénario inconnu : {self.fault_type}. Options : {list(SCENARIOS)}")
        path = DATA_DIR / SCENARIOS[self.fault_type]
        df = pd.read_csv(path)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        self._df = df.sort_values("timestamp").reset_index(drop=True)

    def __len__(self):
        return len(self._df)

    def step(self, i: int) -> dict:
        row = self._df.iloc[i].to_dict()
        hint = None if self.blind else self.fault_type
        return _execute_pipeline_step(row, i, self._buffers, self._m1_history, self._m4_history, self.blind, hint)

    def replay(self, realtime: bool = False) -> Iterator[dict]:
        prev_ts = None
        for i in range(len(self._df)):
            result = self.step(i)
            if realtime and prev_ts is not None:
                cur_ts = self._df.iloc[i]["timestamp"]
                gap = (cur_ts - prev_ts).total_seconds() / max(self.speed, 0.01)
                time.sleep(max(gap, 0))
            prev_ts = self._df.iloc[i]["timestamp"]
            yield result

    def reset(self):
        self._buffers.reset()
        self._m1_history.clear()
        self._m4_history.clear()


@dataclass
class RawRunPlayer:
    """Rejeu BRUT d'un run complet (tous les services, non filtré) -- simule
    exactement ce qu'un collector_final.py enverrait en production. Toujours en
    mode aveugle : la plateforme ne reçoit jamais fault_type/fault_phase pendant le
    rejeu, et le lissage M1 n'a aucun indice sur le type de panne réel."""

    dataset_path: Path
    speed: float = 1.0
    _df: pd.DataFrame = field(init=False, repr=False)
    _buffers: ServiceBufferStore = field(default_factory=ServiceBufferStore, init=False)
    _m1_history: dict = field(default_factory=dict, init=False)
    _m4_history: dict = field(default_factory=dict, init=False)

    def __post_init__(self):
        df = pd.read_csv(self.dataset_path)
        missing = REQUIRED_RAW_COLUMNS - set(df.columns)
        if missing:
            raise ValueError(f"Colonnes manquantes dans le CSV uploadé : {sorted(missing)}")
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        # Ordre EXACT de collecte : timestamp puis service_name à égalité, comme le
        # collector les écrirait au fil de l'eau -- pas de tri qui isolerait un service.
        self._df = df.sort_values(["timestamp", "service_name"]).reset_index(drop=True)

    def __len__(self):
        return len(self._df)

    @property
    def run_id(self) -> str:
        return str(self._df["run_id"].iloc[0])

    @property
    def n_services(self) -> int:
        return self._df["service_name"].nunique()

    def reveal_truth(self) -> dict:
        """Vérité terrain calculée directement depuis les colonnes du CSV -- jamais
        transmise pendant le rejeu, seulement à l'appel explicite de cette méthode."""
        df = self._df
        during = df[df["fault_phase"] == "during_fault"] if "fault_phase" in df.columns else df
        fault_types = [f for f in during.get("fault_type", pd.Series(dtype=object)).unique() if f and f != "none"]
        # Le service réellement affecté = celui qui a un time_to_failure_sec renseigné
        # (OOM) ou, à défaut, celui avec le plus de restarts pendant during_fault.
        target_service = None
        if "time_to_failure_sec" in df.columns and df["time_to_failure_sec"].notna().any():
            target_service = df.loc[df["time_to_failure_sec"].notna(), "service_name"].mode().iat[0]
        elif "restart_count_delta" in during.columns and len(during):
            totals = during.groupby("service_name")["restart_count_delta"].sum()
            if totals.max() > 0:
                target_service = totals.idxmax()
        return {
            "available": True,
            "fault_type": fault_types[0] if fault_types else "none",
            "run_id": self.run_id,
            "service_name": target_service or "indéterminé (voir journal)",
        }

    def step(self, i: int) -> dict:
        row = self._df.iloc[i].to_dict()
        # Toujours aveugle : aucun indice de fault_type n'est disponible pour le lissage.
        return _execute_pipeline_step(row, i, self._buffers, self._m1_history, self._m4_history, True, None)

    def replay(self, realtime: bool = False) -> Iterator[dict]:
        prev_ts = None
        for i in range(len(self._df)):
            result = self.step(i)
            if realtime and prev_ts is not None:
                cur_ts = self._df.iloc[i]["timestamp"]
                gap = (cur_ts - prev_ts).total_seconds() / max(self.speed, 0.01)
                time.sleep(max(gap, 0))
            prev_ts = self._df.iloc[i]["timestamp"]
            yield result


def save_uploaded_csv(file_bytes: bytes) -> str:
    """Sauvegarde un CSV uploadé sur disque, retourne un dataset_id pour le rejeu."""
    dataset_id = uuid.uuid4().hex[:12]
    path = UPLOADS_DIR / f"{dataset_id}.csv"
    path.write_bytes(file_bytes)
    return dataset_id


def uploaded_csv_path(dataset_id: str) -> Path:
    path = UPLOADS_DIR / f"{dataset_id}.csv"
    if not path.exists():
        raise FileNotFoundError(f"Dataset introuvable : {dataset_id}")
    return path
