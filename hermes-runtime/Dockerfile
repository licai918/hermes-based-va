# syntax=docker/dockerfile:1
#
# Gateway image -> Cloud Run service `toee-hermes-gateway` (ADR-0098, ADR-0139, #33).
#
# This builds the PYTHON FastAPI gateway (hermes-runtime), NOT the stale TypeScript
# Fastify gateway named in ADR-0098 (superseded by the Python runtime per ADR-0139;
# see docs/ops/deploy-cloud-run.md). The ASGI app is assembled fail-closed by
# hermes_runtime.gateway_composition:build_gateway_app.
#
# Build context MUST be the repo root so both source trees are present: hermes-runtime
# declares an editable path dependency on ../hermes (toee-hermes) in pyproject.toml,
# so uv needs hermes/ alongside hermes-runtime/ to resolve the lock.
#
#   docker build -f hermes-runtime/Dockerfile -t toee-hermes-gateway .

FROM python:3.11-slim

# git: hermes-agent is pinned to an exact git rev (ADR-0101) and fetched by uv at
# sync time. uv: the project's resolver/installer (ADR-0139). No build toolchain is
# needed — the locked deps (pydantic-core, uvloop, httptools, pillow) ship wheels.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv

# Copy mode avoids hardlink warnings when the venv and cache differ in the image.
ENV UV_LINK_MODE=copy

WORKDIR /app
# ponytail: both trees are copied before `uv sync` because the editable path dep
# (toee-hermes -> ../hermes) is built from source, so a deps-only pre-layer would
# fail without hermes/. Ceiling: coarse layer caching (any hermes/ change re-syncs);
# upgrade path is `uv export` to a separate locked requirements layer if it bites.
COPY hermes/ ./hermes/
COPY hermes-runtime/ ./hermes-runtime/

WORKDIR /app/hermes-runtime
# --frozen installs exactly the committed uv.lock (the single pinned SDK rev).
RUN uv sync --frozen

# Cloud Run injects $PORT (default 8080) and routes to it; bind 0.0.0.0. The factory
# fails closed at boot when a required secret is missing (webhook/internal-job
# secrets, SimpleTexting token, OpenRouter key) — see gateway_composition.build_gateway_app.
ENV PORT=8080
EXPOSE 8080
CMD ["sh", "-c", "uv run --frozen uvicorn hermes_runtime.gateway_composition:build_gateway_app --factory --host 0.0.0.0 --port ${PORT:-8080}"]
