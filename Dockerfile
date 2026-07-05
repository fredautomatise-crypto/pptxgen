# Image tout-en-un : Python + dépendances de génération PPTX.
# Depuis la suppression de l'audio/vidéo, plus besoin de LibreOffice/FFmpeg :
# python-pptx génère directement le fichier .pptx sans étape de rendu.

FROM python:3.11-slim

# fonts-liberation, fonts-crosextra-caladea/carlito : fallback sur des polices
#   proches de Cambria/Calibri (non libres) si elles ne sont pas disponibles
#   sur la machine qui ouvrira le PPTX. Pas strictement nécessaire côté
#   génération (python-pptx n'a pas besoin des polices installées), gardé
#   pour cohérence visuelle si une prévisualisation est ajoutée plus tard.
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-liberation \
    fonts-crosextra-caladea \
    fonts-crosextra-carlito \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/output /app/cache

# Exécution en utilisateur non-root (bonne pratique, même pour un usage local)
RUN useradd --create-home --shell /bin/bash appuser \
    && chown -R appuser:appuser /app
USER appuser

# Streamlit par défaut ; utiliser `docker run ... python main.py ...` pour le CLI
EXPOSE 8501
ENV STREAMLIT_SERVER_ADDRESS=0.0.0.0
ENV STREAMLIT_SERVER_HEADLESS=true

CMD ["streamlit", "run", "webapp/app.py", "--server.port", "8501", "--server.address", "0.0.0.0", "--server.enableCORS", "false", "--server.enableXsrfProtection", "false"]
