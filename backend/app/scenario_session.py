"""
Session de scénario pilotable en direct.

Encapsule un ScenarioPlayer avec les contrôles nécessaires à une démo live pilotée
depuis le frontend : démarrer, mettre en pause, reprendre, changer la vitesse, arrêter.
Une seule session à la fois (suffisant pour une démo jury sur un poste) — on pourrait
passer à une session par websocket/utilisateur si le besoin apparaît plus tard.

Mode aveugle (`blind=True`) : le point du test est que la plateforme réagisse à des
données qu'elle n'a jamais vues étiquetées à l'avance -- exactement le rôle réel de
M1/M2/M3/M4 en production. Concrètement :
  - en mode "start_random", le fault_type est tiré au sort CÔTÉ SERVEUR (random.choice) ;
    même la personne qui pilote la démo ne sait pas lequel avant la révélation.
  - tant que blind=True, `ground_truth_label`/`ground_truth_phase` sont retirés de
    CHAQUE message "step" envoyé au frontend -- ce n'est pas juste caché à l'écran,
    l'info ne transite jamais sur le websocket pendant le rejeu.
  - la vérité (fault_type réel, run_id, service) n'est révélée que sur l'action
    explicite "reveal", envoyée par le frontend quand le jury veut comparer le
    diagnostic du pipeline à la réalité.
"""

import asyncio
import logging
import math
import random
from pathlib import Path

from fastapi import WebSocket

from .m4_demo_engine import M4DemoPlayer
from .scenario_engine import SCENARIOS, RawRunPlayer, ScenarioPlayer

logger = logging.getLogger("nexshop.scenario_session")

MAX_STEP_WAIT_SEC = 4.0  # borne haute du temps d'attente entre 2 points, pour garder une démo vivante
_GROUND_TRUTH_KEYS = ("ground_truth_label", "ground_truth_phase")


def _json_safe(obj):
    """NaN/Infinity ne sont PAS du JSON valide (contrairement à ce que tolère
    silencieusement json.loads en Python) -- le JSON.parse d'un navigateur plante
    dessus. Sur un vrai run brut, cpu_usage_pct (et d'autres métriques) peuvent être
    manquants pour de vraies raisons (scrape raté juste après un restart de pod) et
    finir en NaN au fil du pipeline. On les remplace par null avant tout envoi."""
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    return obj


async def _send_json_safe(websocket: WebSocket, payload: dict):
    await websocket.send_json(_json_safe(payload))


class ScenarioSession:
    def __init__(self):
        self.player: ScenarioPlayer | RawRunPlayer | M4DemoPlayer | None = None
        self.fault_type: str | None = None
        self.speed: float = 5.0
        self.running: bool = False
        self.current_step: int = -1
        self.blind: bool = False
        self.revealed: bool = False
        self.is_raw: bool = False
        self.is_m4_demo: bool = False
        self._task: asyncio.Task | None = None

    async def start(self, websocket: WebSocket, fault_type: str | None, speed: float = 5.0, blind: bool = False, random_pick: bool = False):
        self.stop()
        chosen_fault_type = random.choice(list(SCENARIOS)) if random_pick else fault_type
        self.player = ScenarioPlayer(fault_type=chosen_fault_type, speed=speed, blind=blind)
        self.fault_type = chosen_fault_type
        self.speed = speed
        self.blind = blind
        self.revealed = False
        self.is_raw = False
        self.is_m4_demo = False
        self.running = True
        self.current_step = -1
        self._task = asyncio.create_task(self._run(websocket))

    async def start_raw(self, websocket: WebSocket, dataset_path: Path, speed: float = 5.0):
        """Rejeu brut d'un run complet uploadé -- toujours aveugle par construction
        (cf. RawRunPlayer). Ni le fault_type ni le service cible ne sont connus tant
        que 'reveal' n'a pas été demandé explicitement."""
        self.stop()
        self.player = RawRunPlayer(dataset_path=dataset_path, speed=speed)
        self.fault_type = None
        self.speed = speed
        self.blind = True
        self.revealed = False
        self.is_raw = True
        self.is_m4_demo = False
        self.running = True
        self.current_step = -1
        self._task = asyncio.create_task(self._run(websocket))

    async def start_m4_demo(self, websocket: WebSocket, speed: float = 5.0):
        """Scénario pédagogique DÉDIÉ à M4 (seuil dynamique ARIMA) -- découplé du
        pipeline M1->M2->M3->M4 complet. Rejoue les 4 phases (trafic normal, montée
        de charge légitime, spike brutal, recovery) sur une seule métrique/service ;
        montre qu'un CPU=90% peut être NORMAL (ex. Black Friday) ou une ALERTE
        (trafic calme) selon le contexte récent, pas une valeur absolue. Rien à
        cacher ici : pas de mode aveugle, la vérité (phase) est déjà dans chaque
        point rejoué."""
        self.stop()
        self.player = M4DemoPlayer(speed=speed)
        self.fault_type = None
        self.speed = speed
        self.blind = False
        self.revealed = True
        self.is_raw = False
        self.is_m4_demo = True
        self.running = True
        self.current_step = -1
        self._task = asyncio.create_task(self._run(websocket))

    async def _run(self, websocket: WebSocket):
        assert self.player is not None
        df = self.player._df
        prev_ts = None
        try:
            started_msg = {
                "event": "scenario_started",
                # En mode aveugle, le type de panne n'est PAS envoyé au frontend --
                # personne (pas même l'écran) ne sait ce qui a été injecté.
                "fault_type": None if self.blind else self.fault_type,
                "blind": self.blind,
                "raw": self.is_raw,
                "m4_demo": self.is_m4_demo,
                "total_steps": len(df),
            }
            if self.is_raw:
                started_msg["n_services"] = self.player.n_services
            await _send_json_safe(websocket, started_msg)
            for i in range(len(df)):
                while not self.running:
                    await asyncio.sleep(0.1)
                result = self.player.step(i)
                self.current_step = i
                if self.blind and not self.is_raw:
                    result = {k: v for k, v in result.items() if k not in _GROUND_TRUTH_KEYS}
                await _send_json_safe(websocket, {"event": "step", "data": result})

                cur_ts = df.iloc[i]["timestamp"]
                if prev_ts is not None:
                    gap = (cur_ts - prev_ts).total_seconds() / max(self.speed, 0.01)
                    await asyncio.sleep(min(max(gap, 0.05), MAX_STEP_WAIT_SEC))
                prev_ts = cur_ts
            await _send_json_safe(websocket, {"event": "scenario_complete", "blind": self.blind})
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.exception("Erreur pendant le rejeu du scénario")
            try:
                await _send_json_safe(websocket, {"event": "error", "message": str(e)})
            except Exception:
                pass

    def reveal(self) -> dict:
        """Vérité terrain du dernier scénario joué -- appelé uniquement sur demande
        explicite du frontend (action 'reveal'), jamais poussé automatiquement."""
        if self.player is None:
            return {"available": False}
        self.revealed = True
        if self.is_raw:
            return self.player.reveal_truth()
        df = self.player._df
        return {
            "available": True,
            "fault_type": self.fault_type,
            "run_id": str(df["run_id"].iloc[0]),
            "service_name": str(df["service_name"].iloc[0]),
        }

    def pause(self):
        self.running = False

    def resume(self):
        self.running = True

    def set_speed(self, speed: float):
        self.speed = max(speed, 0.1)

    def stop(self):
        if self._task and not self._task.done():
            self._task.cancel()
        self.running = False
        self.current_step = -1
