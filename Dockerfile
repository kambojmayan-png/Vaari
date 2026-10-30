# Vaari pilot image: the API and the built web app on one port, running as a non-root user.
# Build:  docker compose build      Run: see docs/DEPLOY.md
ARG NODE_IMAGE=node:22-slim
ARG PYTHON_IMAGE=python:3.12-slim

# ---- 1. Build the web app -------------------------------------------------
FROM ${NODE_IMAGE} AS web
WORKDIR /build/web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# ---- 2. Runtime ------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    VAARI_ENV=production \
    VAARI_DB_PATH=/data/vaari.sqlite \
    VAARI_DATA_DIR=/data \
    VAARI_BACKUP_DIR=/data/backups

RUN groupadd --system --gid 10001 vaari \
 && useradd --system --uid 10001 --gid vaari --home-dir /app --no-create-home --shell /usr/sbin/nologin vaari

WORKDIR /app
COPY requirements.txt ./
RUN python -m venv /opt/venv && /opt/venv/bin/pip install -r requirements.txt
ENV PATH=/opt/venv/bin:$PATH

COPY app/ app/
COPY migrations/ migrations/
COPY alembic.ini tasks.py ./
COPY --from=web /build/web/dist web/dist

RUN mkdir -p /data && chown vaari:vaari /data
USER vaari:vaari
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/ready', timeout=4).status == 200 else 1)"]

# The app refuses to start if VAARI_SECRET_KEY or other settings are unsafe (see docs/DEPLOY.md).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--log-config", "app/uvicorn_logging.json"]
