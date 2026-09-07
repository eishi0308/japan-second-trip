# syntax=docker/dockerfile:1.7
# Multi-stage: dependencies are resolved once in a builder, then only the venv
# and source are copied into a slim runtime that runs as a non-root user.
FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /build
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy manifests first so a source-only change does not invalidate the
# dependency layer.
COPY packages/shared_schemas/pyproject.toml packages/shared_schemas/
COPY packages/travel_mcp/pyproject.toml packages/travel_mcp/
COPY apps/api/pyproject.toml apps/api/

COPY packages/shared_schemas packages/shared_schemas
COPY packages/travel_mcp packages/travel_mcp
COPY apps/api apps/api

RUN pip install --upgrade pip setuptools wheel \
 && pip install ./packages/shared_schemas \
 && pip install ./packages/travel_mcp \
 && pip install ./apps/api


FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    ENVIRONMENT=production

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl libpq5 \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 10001 jst

COPY --from=builder /opt/venv /opt/venv
WORKDIR /app
COPY --chown=jst:jst apps/api/src /app/src
COPY --chown=jst:jst apps/api/alembic.ini /app/alembic.ini
COPY --chown=jst:jst scripts /app/scripts
COPY --chown=jst:jst evals /app/evals

USER jst
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD curl -fsS http://localhost:8000/health || exit 1

# Migrations and seeding run in the entrypoint so a fresh environment comes up
# usable; both are idempotent.
COPY --chown=jst:jst apps/api/docker-entrypoint.sh /app/docker-entrypoint.sh
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["uvicorn", "jst_api.main:app", "--host", "0.0.0.0", "--port", "8000", "--app-dir", "/app/src"]
