"""
Buffer glissant par (run_id, service_name).

Pourquoi ce module existe :
Les 3 modèles M1/M2/M3 ont tous été entraînés avec des features "fenêtre glissante"
(rolling mean/std, delta, taux de variation) calculées avec pandas.groupby(...).transform(...)
sur un dataset complet et trié chronologiquement.

En inférence live (une mesure à la fois, comme le fera la vraie démo / le vrai cluster),
on ne peut pas rejouer tout l'historique à chaque point. La solution retenue -- volontairement
simple et fidèle à l'entraînement -- est de garder un buffer des N dernières mesures brutes
par service, et de ré-appliquer EXACTEMENT la même fonction pandas sur ce petit buffer à
chaque nouvelle mesure. Comme les rolling/diff ne regardent que vers l'arrière, le résultat
sur la dernière ligne du buffer est rigoureusement identique à ce qu'on aurait obtenu en
calculant sur tout l'historique complet -- à condition que le buffer soit au moins aussi long
que la plus grande fenêtre utilisée (5 points ici, on garde une marge à 30).
"""

from collections import defaultdict, deque
from typing import Dict, List

MAX_BUFFER_LEN = 30


class ServiceBufferStore:
    """Garde un buffer de mesures brutes (dict) par clé (run_id, service_name)."""

    def __init__(self, max_len: int = MAX_BUFFER_LEN):
        self.max_len = max_len
        self._buffers: Dict[tuple, deque] = defaultdict(lambda: deque(maxlen=self.max_len))

    def push(self, run_id: str, service_name: str, row: dict) -> List[dict]:
        """Ajoute une mesure et retourne le buffer courant (liste de dicts, ordre chronologique)."""
        key = (run_id, service_name)
        self._buffers[key].append(row)
        return list(self._buffers[key])

    def get(self, run_id: str, service_name: str) -> List[dict]:
        return list(self._buffers.get((run_id, service_name), []))

    def reset(self, run_id: str | None = None):
        """Vide tous les buffers, ou seulement ceux d'un run donné (nouveau scénario démo)."""
        if run_id is None:
            self._buffers.clear()
        else:
            keys_to_drop = [k for k in self._buffers if k[0] == run_id]
            for k in keys_to_drop:
                del self._buffers[k]
