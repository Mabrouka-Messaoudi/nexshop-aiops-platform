"""
M4 Demo Engine — scénario pédagogique DÉDIÉ au seuil dynamique (ARIMA glissant).

Contrairement aux scénarios curés de scenario_engine.py (qui rejouent une panne
multi-métriques à travers TOUT le pipeline M1→M2→M3→M4), ce scénario ne concerne
que M4 et une seule métrique (cpu_usage_pct), sur un service fictif. Objectif :
montrer que "seuil dynamique" ne veut pas dire "seuil fixe recalculé une fois",
mais bien un seuil qui suit le CONTEXTE récent :

    trafic normal (CPU~43%)         -> bande ~[40-46]  -> NORMAL
    montée de charge légitime       -> bande s'élargit  -> NORMAL (pas d'alerte,
                                        contrairement à un seuil fixe qui sonnerait)
    Black Friday soutenu (CPU~91%)  -> bande ~[86-96]   -> NORMAL (même chose : très
                                        haut en absolu, mais légitime pour CE contexte)
    spike brutal (CPU~99%, au-delà  -> hors bande       -> ALERT (le seul vrai
    même du niveau Black Friday)                           incident du scénario)
    recovery                        -> bande redescend  -> NORMAL

Les valeurs de CPU sont pré-générées une fois (data/scenario_m4_demo.csv, 7 phases,
avec une transition lissée entre phases pour ne pas simuler un faux "step" qui
n'existerait pas dans un vrai ramp-up) mais le calcul du seuil dynamique lui-même
est fait EN DIRECT, point par point, par le vrai moteur ARIMA de m4_threshold.py —
rien n'est pré-calculé ni scripté côté résultat.
"""

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

import pandas as pd

from . import m4_threshold

DATA_DIR = Path(__file__).parent.parent / "data"
M4_DEMO_CSV = DATA_DIR / "scenario_m4_demo.csv"


@dataclass
class M4DemoPlayer:
    """Rejeu du scénario pédagogique M4 (4 phases). Une seule métrique, un seul
    service fictif -- volontairement découplé du pipeline M1-M4 complet."""

    speed: float = 1.0
    _df: pd.DataFrame = field(init=False, repr=False)
    _cpu_history: list = field(default_factory=list, init=False)

    def __post_init__(self):
        df = pd.read_csv(M4_DEMO_CSV)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        self._df = df.sort_values("step").reset_index(drop=True)

    def __len__(self):
        return len(self._df)

    def step(self, i: int) -> dict:
        row = self._df.iloc[i].to_dict()
        self._cpu_history.append(float(row["cpu_usage_pct"]))
        m4_result = m4_threshold.predict(self._cpu_history, metric_name="cpu_usage_pct")
        return {
            "step": int(row["step"]),
            "timestamp": str(row["timestamp"]),
            "run_id": row["run_id"],
            "service_name": row["service_name"],
            "phase": row["phase"],
            "cpu_usage_pct": row["cpu_usage_pct"],
            "m4": m4_result,
        }

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
        self._cpu_history.clear()
