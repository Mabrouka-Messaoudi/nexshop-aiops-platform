# NexShop AIOps Command Center — Frontend (Lot 3)

React + Vite. Direction visuelle : salle de contrôle Ops (NOC), pas un dashboard
générique — élément signature : le **rail de pipeline** (M1→M2→M3→M4) qui s'illumine
en temps réel au passage de chaque mesure, comme un vrai circuit.

## Lancer en local

```bash
cd frontend
npm install
npm run dev
```

Par défaut, l'app appelle le backend sur `http://localhost:8000` (voir `.env`,
variable `VITE_API_URL`) — démarre le backend du Lot 2 en parallèle :

```bash
cd backend && uvicorn app.main:app --reload --port 8000
```

## Les 4 vues

1. **Cockpit** — sélection d'un scénario de panne réel, lecture avec contrôle
   play/pause/vitesse, carte du cluster (le service concerné s'illumine selon la
   sévérité), pipeline M1→M2→M3→M4 animé (avec explication en direct : les features
   au z-score le plus élevé quand M1 déclenche une alerte), journal d'événements.
2. **Tester un modèle** — formulaire de métriques (sliders) envoyé directement aux
   4 endpoints REST indépendants, résultats enrichis (features contributives M1,
   probabilités M2, déviation M4).
3. **Explicabilité** — sur quoi s'appuie chaque modèle : importance globale des
   features (M2/M3, `feature_importances_` réel du modèle entraîné), méthode
   d'explication par instance pour M1, déviation en écarts-types pour M4.
4. **Performance** — vraies métriques d'évaluation des 4 modèles (recall M1 par
   type de panne, F1 par classe M2, MAE/R² M3, comparaison seuil fixe vs ARIMA M4),
   servies par `/models/metrics`.

**Mode présentation** : bouton "⤢ Présentation" en haut à droite — masque la barre
latérale et passe en plein écran navigateur, pour la soutenance.

## Vérifications faites

- `npx oxlint src` → 0 warning, 0 erreur
- `npm run build` → build de production propre
- Backend + frontend démarrés en parallèle en local ; WebSocket testé bout-en-bout,
  y compris la nouvelle explicabilité M1 (`top_features` reçus en direct dès la
  première alerte d'un scénario)

## Structure

```
frontend/
  src/
    components/     SideNav, TopBar, ScenarioControls, ServiceMap,
                     PipelineRail (élément signature), EventLog
    pages/           Cockpit.jsx, TestModels.jsx, Performance.jsx
    lib/             api.js (client REST), useScenarioSocket.js (hook WebSocket)
    styles/          tokens.css (palette/typo), layout.css
  .env               VITE_API_URL
```

## Prochaine étape suggérée (Lot 5)

- Favicon/OG déjà en place ; reste à peaufiner l'empty-state / responsive mobile fin
- Export PDF ou capture d'écran automatique du cockpit pour le rapport PFE
- Authentification légère si la démo doit être exposée au-delà du poste local
