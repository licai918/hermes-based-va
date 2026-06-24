# syntax=docker/dockerfile:1
#
# Workbench image -> Cloud Run service `toee-hermes-workbench` (ADR-0098, #33).
#
# Build context MUST be the repo root: this is a pnpm workspace, so the build needs
# the root lockfile + the sibling workspace packages (@toee/shared, @toee/hermes-runtime,
# @toee/domain-adapters) that apps/workbench depends on.
#
#   docker build -f apps/workbench/Dockerfile -t toee-hermes-workbench .
#
# Ignore rules (node_modules, .next, etc.) live in the repo-root .dockerignore — the
# only ignore file Docker honors for a root-context build; there is intentionally no
# per-package apps/workbench/.dockerignore (it would be dead config here).

FROM node:20-slim AS base
ENV PNPM_HOME=/pnpm
ENV PATH="$PNPM_HOME:$PATH"
# corepack pins pnpm to the version in the root package.json "packageManager" field.
RUN corepack enable
WORKDIR /app

# --- builder: install the frozen workspace, then build the standalone bundle ---
FROM base AS builder
# Copy manifests first so the (slow) install layer caches across source-only changes.
# Every workspace package.json the lockfile references must be listed here; add new
# workspace packages to this block when they appear in pnpm-workspace.yaml.
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/workbench/package.json ./apps/workbench/
COPY packages/shared/package.json ./packages/shared/
COPY packages/hermes-runtime/package.json ./packages/hermes-runtime/
COPY packages/domain-adapters/package.json ./packages/domain-adapters/
COPY packages/eval-runner/package.json ./packages/eval-runner/
COPY services/hermes-gateway/package.json ./services/hermes-gateway/
RUN pnpm install --frozen-lockfile

COPY . .
# Next emits a self-contained server under apps/workbench/.next/standalone. Because
# next.config.ts sets outputFileTracingRoot to the repo root, the standalone tree
# preserves the monorepo layout (server at apps/workbench/server.js, traced deps in
# a top-level node_modules).
RUN pnpm --filter @toee/workbench build

# --- runner: only the standalone output, no pnpm store or source ---
FROM node:20-slim AS runner
ENV NODE_ENV=production
# Next's standalone server reads PORT (Cloud Run injects it) and HOSTNAME; bind all
# interfaces so the container is reachable.
ENV PORT=3000
ENV HOSTNAME=0.0.0.0
WORKDIR /app

# Standalone bundle (includes the traced node_modules + the monorepo dir layout),
# then the static assets it serves. apps/workbench has no public/ dir today; add a
# `COPY --from=builder /app/apps/workbench/public ./apps/workbench/public` here if one
# is introduced.
COPY --from=builder /app/apps/workbench/.next/standalone ./
COPY --from=builder /app/apps/workbench/.next/static ./apps/workbench/.next/static

EXPOSE 3000
# Standalone entrypoint per Next's monorepo output layout (server.js nested under the
# app's path from the tracing root).
CMD ["node", "apps/workbench/server.js"]
