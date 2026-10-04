# nexshop-aiops-platform – Plateforme AIOps de NexShop (backend + cockpit)

Ce dépôt met en production les quatre modèles de mon PFE
([`nexshop-aiops-models`](https://github.com/Mabrouka-Messaoudi/nexshop-aiops-models)). Il se compose de
deux parties :

- **backend/** : une API FastAPI qui charge les modèles entraînés et les enchaîne en cascade. M1 détecte
  une anomalie. Seulement dans ce cas, M2 identifie la panne. Si M2 conclut à un OOM, M3 estime le temps
  restant avant le crash. M4 juge en parallèle chaque métrique par rapport à son seuil dynamique.
- **frontend/** : le *Command Center*, une interface React qui rejoue des pannes réelles et montre en
  direct la décision de chaque modèle. On peut aussi y tester chaque modèle isolément, consulter leurs
  performances et leur explicabilité, ou suivre le cluster en direct.

```
Collecteur ──POST /ingest/tick──► backend (FastAPI, :30080) ──WebSocket──► Cockpit (React, :30081)
                                   M1 → M2 → M3, M4 en parallèle
```

## Modes de démonstration

| Mode | Principe |
|------|----------|
| Démo pédagogique | Rejeu d'une panne réelle nommée (OOM, CrashLoop, DB Down, CPU Throttle) |
| Mystère | Une panne tirée au sort côté serveur. Le diagnostic est comparé à la vérité seulement après la révélation. |
| Upload | Rejeu d'un CSV brut du collecteur (tous les pods). Le pipeline doit trouver lui-même le service touché. |
| Démo M4 | Montée jusqu'à un Black Friday soutenu, puis un vrai pic : comparaison avec un seuil fixe à 80 % |
| Live | Le collecteur envoie chaque mesure à `/ingest/tick` et le cockpit affiche le diagnostic en temps réel |

Dans les modes mystère et upload, aucune information sur la panne réelle n'est utilisée par le pipeline.
Le détail est dans `backend/README.md`.

## Lancer en local

```bash
cd backend && pip install -r requirements.txt && uvicorn app.main:app --port 8000
cd frontend && npm install && npm run dev        # http://localhost:5173
```

Documentation interactive de l'API : <http://localhost:8000/docs>.

## Déploiement sur GKE

Prérequis : le cluster et la stack de monitoring du dépôt
[`nexshop-gke`](https://github.com/Mabrouka-Messaoudi/nexshop-gke), Docker, et un compte Docker Hub.

```bash
# 1. Images
docker build -t mabroukamessaoudi1/nexshop-aiops-backend:latest backend
docker build --build-arg VITE_API_URL=http://nexshop-mab.duckdns.org:30080 \
  -t mabroukamessaoudi1/nexshop-aiops-cockpit:latest frontend
docker push mabroukamessaoudi1/nexshop-aiops-backend:latest
docker push mabroukamessaoudi1/nexshop-aiops-cockpit:latest

# 2. Kubernetes
kubectl apply -f k8s/backend.yaml
kubectl apply -f k8s/cockpit.yaml
```

| Composant | Namespace | Accès |
|-----------|-----------|-------|
| Backend | `monitoring` (nœud de monitoring) | `http://nexshop-mab.duckdns.org:30080` (`/health`, `/docs`) |
| Cockpit | `nexshop` | `http://nexshop-mab.duckdns.org:30081` |

L'URL du backend est intégrée dans le JavaScript **au moment du build** du cockpit. Comme c'est le
navigateur qui l'appelle, il faut un nom public (DuckDNS) et non un nom DNS interne au cluster. Si l'URL
change, il faut reconstruire l'image.

## Limites connues

- Les CSV uploadés sont stockés dans un `emptyDir` : ils disparaissent au redémarrage du pod.
- `/ingest/tick` est ouvert par défaut. Pour le protéger, créer le Secret décrit en bas de
  `k8s/backend.yaml` (variable `INGEST_TOKEN`).
- CORS ouvert à toutes les origines, ce qui convient à une démo mais pas à la production.
