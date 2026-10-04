from typing import Any, Optional

from pydantic import BaseModel, Field


class MetricRow(BaseModel):
    """Une mesure brute de service, au format exact des CSV NexShop.
    Champs volontairement libres (dict) car les 3 modèles n'utilisent pas tous
    les mêmes colonnes, et pour rester tolérant à un buffer live incomplet."""
    model_config = {"extra": "allow"}

    run_id: str
    service_name: str
    timestamp: str
    cpu_usage_pct: Optional[float] = None
    memory_usage_pct: Optional[float] = None


class HistoryRequest(BaseModel):
    """Historique brut d'un service, du plus ancien au plus récent. Le dernier point
    est celui pour lequel la prédiction est calculée ; les précédents ne servent qu'à
    reconstituer les features de fenêtre glissante (identique à l'entraînement)."""
    history: list[dict[str, Any]] = Field(..., min_length=1)


class M4Request(BaseModel):
    metric_history: list[float] = Field(..., min_length=1)
    metric_name: str = "cpu_usage_pct"


class ScenarioStartRequest(BaseModel):
    fault_type: str
    speed: float = 5.0
