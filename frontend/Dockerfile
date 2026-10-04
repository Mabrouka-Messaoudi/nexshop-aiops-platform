# Build multi-étapes : compile avec Node, sert les fichiers statiques avec nginx
# (léger, pas besoin de garder Node dans l'image finale).

FROM node:20-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .

# VITE_API_URL est figé au moment du BUILD (Vite l'inline dans le JS final, pas
# modifiable après coup sans reconstruire) -- utilise le hostname DuckDNS plutôt
# qu'une IP de nœud en dur, pour survivre à un redimensionnement du cluster tant
# que DuckDNS reste à jour (déjà automatisé par run_oom_scenario_v2.sh à chaque
# run). C'est le NAVIGATEUR de la personne qui charge la Cockpit qui doit joindre
# cette URL, pas le cluster lui-même -- donc jamais de nom DNS interne
# *.svc.cluster.local ici, contrairement aux datasources Grafana.
ARG VITE_API_URL=http://nexshop-mab.duckdns.org:30080
ENV VITE_API_URL=${VITE_API_URL}
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
