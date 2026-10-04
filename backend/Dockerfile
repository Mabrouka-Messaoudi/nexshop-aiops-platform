# Python 3.12 -- même version que celle utilisée pour valider les artefacts
# scikit-learn (numpy==2.4.4, scikit-learn==1.8.0, cf. requirements.txt) tout au
# long de ce projet. Ne PAS changer de version majeure de Python sans revalider
# le chargement des .joblib/.pkl (cf. les bugs de compat déjà rencontrés).
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .

# libgomp1 : requis au runtime par scikit-learn (OpenMP).
# build-essential : filet de sécurité si une dépendance n'a pas de wheel précompilé
# pour cette architecture -- installé puis retiré dans la même couche pour ne pas
# alourdir l'image finale.
#
# Boucle de retry sur "apt-get update" : vécu en pratique -- un miroir Debian
# renvoyant un "Hash Sum mismatch" sur son propre fichier d'index (pas un paquet
# précis, l'index lui-même) a fait planter le build à plusieurs reprises, même
# avec --no-cache. C'est un vrai désync transitoire côté miroir, pas un souci côté
# image -- 5 tentatives avec un court délai suffisent presque toujours à retomber
# sur un nœud CDN cohérent.
RUN for i in 1 2 3 4 5; do \
        apt-get update && break || { echo "apt-get update a échoué (tentative $i/5), nouvelle tentative dans 5s..."; sleep 5; }; \
    done \
    && apt-get install -y --no-install-recommends libgomp1 build-essential \
    && pip install --no-cache-dir -r requirements.txt \
    && apt-get purge -y --auto-remove build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY app ./app
COPY artifacts ./artifacts
COPY data ./data

# data/uploads doit rester inscriptible au runtime (upload de CSV bruts depuis le
# Cockpit) -- en k8s ce sera un emptyDir monté par-dessus, mais on le crée quand
# même ici pour un `docker run` autonome hors cluster.
RUN mkdir -p /app/data/uploads

# Utilisateur non-root -- bonne pratique k8s, pas de raison de tourner en root ici.
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000
ENV PYTHONUNBUFFERED=1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
