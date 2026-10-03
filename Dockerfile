FROM python:3.10-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    RASA_TELEMETRY_ENABLED=false

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl gnupg nginx supervisor \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

COPY server/requirements/rasa.txt server/requirements/actions.txt server/requirements/constraints.txt ./requirements/
RUN pip install --no-cache-dir -c requirements/constraints.txt -r requirements/rasa.txt -r requirements/actions.txt \
    && pip install --no-cache-dir \
    https://github.com/explosion/spacy-models/releases/download/en_core_web_md-3.4.1/en_core_web_md-3.4.1-py3-none-any.whl

COPY server/ ./server/
RUN cd server && rasa train --config rasa/config.yml --domain rasa/domain.yml --data rasa/data \
    --out models --fixed-model-name eco-travel

COPY frontend/ ./frontend/
RUN cd frontend && npm ci && VITE_RASA_URL=/rasa npm run build \
    && cp -r dist/. /usr/share/nginx/html/

COPY docker/nginx.hf.conf /etc/nginx/nginx.conf
COPY docker/supervisord.hf.conf /etc/supervisor/conf.d/eco-travel.conf

RUN useradd --create-home --uid 1000 appuser \
    && chown -R appuser:appuser /app /usr/share/nginx/html /var/lib/nginx /var/log/nginx

USER appuser
EXPOSE 7860
CMD ["sh", "-c", "echo \"nginx: serving the app on port ${PORT:-7860}\" && sed \"s/listen 7860;/listen ${PORT:-7860};/\" /etc/nginx/nginx.conf > /tmp/nginx.conf && exec /usr/bin/supervisord -c /etc/supervisor/conf.d/eco-travel.conf"]
