# syntax=docker/dockerfile:1
FROM node:22.23.0-bookworm-slim@sha256:d9f850096136edbc402debdd8729579a288aac64574ada0ff4db26b6ae58b0b2 AS frontend
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/proxy_ca; fi; \
    npm ci --strict-ssl=true
COPY frontend/ ./
RUN npm run build

FROM python:3.12.13-slim-bookworm@sha256:4766d8b510c428e595d74b9cc5bbb2fae8e26316fffb4adc89908d79aacd58a2 AS backend
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN --mount=type=secret,id=system_ca \
    if [ -f /run/secrets/system_ca ]; then export PIP_CERT=/run/secrets/system_ca; fi; \
    pip install --no-cache-dir uv==0.12.1
RUN --mount=type=secret,id=system_ca \
    if [ -f /run/secrets/system_ca ]; then export SSL_CERT_FILE=/run/secrets/system_ca; fi; \
    uv sync --frozen --no-dev --no-install-project
COPY backend/ ./backend/
COPY alembic.ini ./
COPY --from=frontend /build/frontend/dist/ ./frontend/dist/
COPY deploy/start.sh ./deploy/start.sh
RUN useradd --system --uid 10001 --create-home clms && \
    install -d -m 0700 -o clms -g clms /var/lib/clms-archive
USER 10001:10001
ENV CLMS_DATA_DIR=/var/lib/clms-archive \
    CLMS_PUBLIC_ORIGIN=http://127.0.0.1:8472 \
    PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1
VOLUME ["/var/lib/clms-archive"]
EXPOSE 8472
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8472/api/health', timeout=3)" || exit 1
ENTRYPOINT ["/app/deploy/start.sh"]
