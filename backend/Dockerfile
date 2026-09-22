FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# System deps for PostGIS/psycopg + build
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Bootstrap du schéma (idempotent) avant le démarrage du serveur:
# tables events (v1.2), event_edge_closure, route_cache, stats + index.
# Échec toléré (DB pas encore prête / déjà bootstrapée) -> uvicorn démarre quand même.
RUN printf '%s\n' \
    '#!/bin/sh' \
    'set -x' \
    'for i in 1 2 3 4 5 6 7 8 9 10; do' \
    '  python manage.py install-schema && break' \
    '  echo "install-schema retry $i/10 (DB pas encore prête?)"' \
    '  sleep 3' \
    'done' \
    'exec "$@"' \
    > /app/entrypoint.sh && chmod +x /app/entrypoint.sh

EXPOSE 8000

# Default command: uvicorn with reload disabled in prod
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
