FROM python:3.10-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl gnupg nginx supervisor \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

COPY server/requirements/rasa.txt server/requirements/actions.txt ./requirements/
RUN pip install --no-cache-dir -r requirements/rasa.txt -r requirements/actions.txt \
    && python -m spacy download en_core_web_md

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
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/supervisord.conf"]
