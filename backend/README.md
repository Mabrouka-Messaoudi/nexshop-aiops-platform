# NexShop AIOps Command Center — Backend

## Lancer le serveur

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Docs interactives auto-générées : http://localhost:8000/docs

## Endpoints

### Test indépendant par modèle
- `POST /m1/predict`   {"history": [...]}                       — score d'anomalie LOF
- `POST /m2/predict`   {"history": [...]}                       — classe de panne
- `POST /m3/predict`   {"history": [...]}                       — temps avant panne OOM
- `POST /m4/predict`   {"metric_history": [...], "metric_name"} — seuil dynamique ARIMA
- `POST /pipeline/run` {"history": [...]}                       — M1→M2→M3→M4 enchaînés

### Métadonnées
- `GET /health`
- `GET /models/metrics`  — vraies métriques d'évaluation des 4 modèles
- `GET /models/explainability` — feature importance globale (M2/M3) + méthode par instance (M1/M4)
- `GET /scenarios`       — scénarios de panne réels curés, disponibles pour le rejeu

### Upload d'un run brut réel (test aveugle authentique)
`POST /scenario/upload` — multipart, champ `file` (CSV). Accepte directement la sortie
de `collector_final.py` (tous les services du cluster, non filtré, comme le CSV que
génère `run_oom_scenario_v2.sh`). Retourne `{dataset_id, n_points, n_services}` — jamais
le contenu ni la vérité terrain du fichier.

### Démo live (WebSocket)
`ws://localhost:8000/ws/scenario`

Client -> serveur :
```json
{"action": "start", "fault_type": "oom", "speed": 5}
{"action": "start_random", "speed": 5, "blind": true}
{"action": "start_upload", "dataset_id": "...", "speed": 5}
{"action": "pause"}
{"action": "resume"}
{"action": "set_speed", "speed": 10}
{"action": "reveal"}
{"action": "reset"}
```

Serveur -> client :
```json
{"event": "scenario_started", "fault_type": ..., "blind": ..., "raw": ..., "total_steps": ...}
{"event": "step", "data": {"...résultat complet du pipeline pour ce point..."}}
{"event": "scenario_complete"}
{"event": "reveal", "fault_type": ..., "run_id": ..., "service_name": ...}
```

`fault_type` ∈ `cpu_throttle`, `crashloop`, `db_down`, `oom` (4 vraies pannes réinjectées,
avec un vrai segment de trafic normal en tête pour la transition vert→rouge).

**Trois modes de rejeu :**
1. **`start`** (démo pédagogique) — scénario nommé, service déjà connu, pour expliquer clairement le fonctionnement.
2. **`start_random`** (mystère aveugle) — un des 4 scénarios curés est tiré au sort côté serveur ; ni le frontend ni la vérité terrain ne transitent avant la révélation explicite.
3. **`start_upload`** (injection réelle) — rejeu BRUT d'un CSV multi-service uploadé (18 pods entrelacés, ordre exact de collecte). Toujours aveugle. Le pipeline découvre lui-même quel service est affecté ; `reveal` compare son diagnostic à la vérité calculée depuis les colonnes du fichier.

## Honnêteté du pipeline (pas d'oracle caché)

- M3 ne se déclenche **jamais** sur le fait qu'on connaît le vrai fault_type : il se
  déclenche uniquement si **M2 lui-même** a classifié le point comme `oom`.
- Le lissage temporel de M1 (fenêtre 3, max vs vote majoritaire) n'utilise le
  `fault_type` réel que dans le mode démo pédagogique NON aveugle. Dès que `blind=True`
  (mystère ou upload), M1 retombe sur sa politique par défaut, sans aucun indice.
- Les résultats sont assainis avant envoi (`_json_safe`) : `NaN`/`Infinity` (métriques
  réellement manquantes sur un run brut, ex. juste après un restart de pod) sont
  convertis en `null` — `NaN` n'est pas du JSON valide et fait planter `JSON.parse()`
  côté navigateur, une vraie limite trouvée en testant sur un run réel non filtré.

## Structure

```
backend/
  app/
    m1_anomaly.py          détection d'anomalie (LOF)
    m2_classification.py   classification de panne (Gradient Boosting)
    m3_prediction.py       prédiction time-to-failure OOM (double modèle quantile)
    m4_threshold.py        seuils dynamiques (ARIMA glissant)
    buffers.py             buffer glissant par service (features temporelles live)
    scenario_engine.py     ScenarioPlayer (curé) + RawRunPlayer (brut multi-service)
    scenario_session.py    rejeu asynchrone pilotable (utilisé par le WebSocket)
    main.py                application FastAPI
  artifacts/                modèles entraînés (.joblib/.pkl) + métadonnées figées
  data/                     4 scénarios curés (CSV) + métriques des modèles
  data/uploads/              CSV uploadés (dont un exemple réel : sample_raw_run.csv)
  test_smoke.py             validation bout-en-bout hors serveur
```

## Notes de fiabilité (trouvées en testant, pas en supposant)

- `mem_limit_mi`/`mem_request_mi` sont des chaînes ("300Mi") dans les CSV bruts M3 — parsées explicitement.
- Le mapping `service_medians` de `cleaning_stats.json` (M1) est indexé par nom de pod
  exact du train, inutilisable en live (pods redéployés) — remplacé par une disponibilité
  empirique par *type* de service (`m1_structural_availability_by_service_type.json`).
- M2 appelé isolément sur du trafic normal peut se tromper (jamais entraîné sur "aucune
  anomalie détectée par M1 mais on demande quand même une classe") — c'est pourquoi le
  pipeline n'appelle M2 que si M1 a détecté une anomalie, jamais en standalone en prod.
- Sur un run brut réel non filtré, `trace_error_span_ratio` est NaN pour les services
  sans tracing (non couvert par les stats de nettoyage figées de M2, qui n'a vu que des
  services tracés à l'entraînement) — filet de sécurité `fillna(0)` ajouté.
- Sur ce même type de run, `cpu_usage_pct` peut être ponctuellement NaN (scrape raté
  juste après un restart de pod) — assaini en `null` avant tout envoi WebSocket.
- Testé avec un vrai run de 18 services / 480 points (uploadé par l'utilisateur) : le
  pipeline a désigné le bon service (`product-service-...`) comme suspect OOM sur 23-24
  points sur 24, sans jamais recevoir la vérité terrain pendant le rejeu.

## Démo dédiée M4 (`/scenarios/m4-demo`, action WebSocket `start_m4_demo`)

Scénario pédagogique séparé du pipeline complet (`app/m4_demo_engine.py` +
`data/scenario_m4_demo.csv`), pensé pour montrer que M4 juge une valeur par rapport au
**contexte récent**, pas à un seuil fixe. 7 phases : normal → montée de charge → charge
soutenue → montée Black Friday → **Black Friday soutenu** (~90%, légitime) → spike
(au-delà même du niveau Black Friday, seul vrai incident) → recovery.

Chaque prédiction M4 inclut désormais une comparaison au seuil fixe classique
(`fixed_alert`, `avoided_false_alarm`, `missed_by_fixed`) — vérifié : pendant le Black
Friday soutenu, M4 déclenche 0/5 alerte contre 5/5 pour un seuil fixe `>80%`. Le spike
est détecté par les deux.
