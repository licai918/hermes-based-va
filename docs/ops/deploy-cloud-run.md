# Cloud Run deploy + smoke (workbench & gateway)

> Master Slice 31 / issue #33. Two deployable images, each with its own Dockerfile
> and its own Cloud Run service. Building and deploying are **manual** steps (run
> from a machine with Docker + `gcloud`); this repo only ships the Dockerfiles, the
> env catalog (`.env.example`), and this runbook.

## Related ADRs

| ADR | Topic |
|-----|-------|
| [0098](../adr/0098-local-dev-and-cloud-run-deployment.md) | Local dev + Cloud Run, per-service Dockerfiles and env layering |
| [0139](../adr/0139-hermes-is-nous-python-agent-plugin-integration.md) | Hermes is the Python `hermes-agent`; the gateway is Python |
| [0129](../adr/0129-composio-credential-and-oauth-hosting.md) | Composio credential hosting (Secret Manager) |

> **ADR-0098 supersession (read this first).** ADR-0098 predates ADR-0139 and names a
> `services/hermes-gateway/Dockerfile` for an old **TypeScript Fastify** gateway. That
> path is **stale**. The gateway is now the **Python FastAPI** runtime in
> `hermes-runtime/`, and its Dockerfile lives at **`hermes-runtime/Dockerfile`**. ADR-0098's
> env-layering and "separate image per service" decisions still hold; only the gateway
> source/path changed (ADR-0139). ADR-0098 now carries an amendment banner pointing here;
> its body is retained as the historical record.

## Services and images

| Cloud Run service | Image | Dockerfile | Build context | Listens on |
|-------------------|-------|------------|---------------|------------|
| `toee-hermes-workbench` | `toee-hermes-workbench` | `apps/workbench/Dockerfile` | repo root | `$PORT` (Next standalone) |
| `toee-hermes-gateway` | `toee-hermes-gateway` | `hermes-runtime/Dockerfile` | repo root | `$PORT` (uvicorn) |

Both Dockerfiles use the **repo root** as the build context:

- The workbench is a pnpm workspace and needs the root lockfile + sibling `packages/*`.
- The gateway's `hermes-runtime` project has an editable path dependency on `../hermes`
  (`toee-hermes`), so `uv` needs both `hermes/` and `hermes-runtime/` present.

Cloud Run injects `$PORT` and routes to it; both entrypoints bind `0.0.0.0:$PORT`.

## Secret Manager → Cloud Run env mapping

Production secrets come from **GCP Secret Manager**; non-secret config is plain env.
Local development uses per-service `.env.local` files instead (ADR-0098) — never bake
secrets into an image. See `.env.example` for the full catalog and which vars each
service reads.

### Gateway (`toee-hermes-gateway`)

The gateway fails closed at boot (`build_gateway_app`) if any **required** secret is
missing.

| Env var | Source | Required? | Notes |
|---------|--------|-----------|-------|
| `SIMPLETEXTING_WEBHOOK_TOKEN` | Secret Manager | yes | Shared token in the registered webhook URL (ADR-0021 — SimpleTexting does not sign payloads) |
| `INTERNAL_JOB_SECRET` | Secret Manager | yes | Guards `/internal/jobs/agent-turn` (ADR-0106) |
| `SIMPLETEXTING_API_TOKEN` | Secret Manager | yes | Outbound SimpleTexting sends (ADR-0083) |
| `OPENROUTER_API_KEY` | Secret Manager | yes | Async agent turn (ADR-0009) |
| `SIMPLETEXTING_ACCOUNT_PHONE` | plain env | no | Sending number; account primary when unset |
| `SIMPLETEXTING_API_BASE_URL` | plain env | no | Defaults to `https://api-app2.simpletexting.com/v2/` |
| `OPENROUTER_BASE_URL` / `OPENROUTER_MODEL` / `OPENROUTER_FALLBACK_MODEL` | plain env | no | Defaults pinned in code (ADR-0009) |
| `INTEGRATION_DRIVER` | plain env | no | `mock` (default) until the integration phase |
| `COMPOSIO_API_KEY` | Secret Manager | **optional until integration phase (#33)** | Only when `INTEGRATION_DRIVER=composio` |
| `COMPOSIO_USER_ID`, `COMPOSIO_{SHOPIFY,QBO,SQUARE}_CONNECTED_ACCOUNT_ID` | plain env | only with composio | See the Composio runbook |

Composio onboarding, link-time `*_AUTH_CONFIG_ID` vars, and per-toolkit smoke live in
[`composio-connected-accounts.md`](./composio-connected-accounts.md).

### Workbench (`toee-hermes-workbench`)

| Env var | Source | Required? | Notes |
|---------|--------|-----------|-------|
| `WORKBENCH_SESSION_SECRET` | Secret Manager | yes | Session signing for username/password auth (ADR-0017) |

## Build + deploy (manual)

Set your project/region/registry once:

```bash
export PROJECT=toee-tire           # GCP project id
export REGION=us-central1          # Cloud Run region
export REPO=us-central1-docker.pkg.dev/$PROJECT/hermes   # Artifact Registry repo
```

### Gateway

```bash
# Build with the REPO ROOT as context (note the trailing dot), gateway Dockerfile.
docker build -f hermes-runtime/Dockerfile -t "$REPO/toee-hermes-gateway:latest" .
docker push "$REPO/toee-hermes-gateway:latest"

gcloud run deploy toee-hermes-gateway \
  --image "$REPO/toee-hermes-gateway:latest" \
  --region "$REGION" \
  --no-allow-unauthenticated \
  --set-secrets="SIMPLETEXTING_WEBHOOK_TOKEN=simpletexting-webhook-token:latest,INTERNAL_JOB_SECRET=internal-job-secret:latest,SIMPLETEXTING_API_TOKEN=simpletexting-api-token:latest,OPENROUTER_API_KEY=openrouter-api-key:latest"
  # Add when wiring Composio (issue #33 / ADR-0129):
  #   --set-secrets=...,COMPOSIO_API_KEY=composio-api-key:latest
  #   --set-env-vars=INTEGRATION_DRIVER=composio,COMPOSIO_USER_ID=toee-staging,COMPOSIO_SHOPIFY_CONNECTED_ACCOUNT_ID=ca_...,COMPOSIO_QBO_CONNECTED_ACCOUNT_ID=ca_...,COMPOSIO_SQUARE_CONNECTED_ACCOUNT_ID=ca_...
```

### Workbench

```bash
# Build with the REPO ROOT as context (pnpm workspace), workbench Dockerfile.
docker build -f apps/workbench/Dockerfile -t "$REPO/toee-hermes-workbench:latest" .
docker push "$REPO/toee-hermes-workbench:latest"

gcloud run deploy toee-hermes-workbench \
  --image "$REPO/toee-hermes-workbench:latest" \
  --region "$REGION" \
  --allow-unauthenticated \
  --set-secrets="WORKBENCH_SESSION_SECRET=workbench-session-secret:latest"
```

`docker build` requires a running Docker daemon. From an environment without one, use
`gcloud builds submit --tag "$REPO/<image>:latest" .` (still repo-root context) instead.

## Staging smoke checklist

Run after the gateway revision is live and **before** sending real traffic. Capture the
service URLs:

```bash
GATEWAY_URL=$(gcloud run services describe toee-hermes-gateway --region "$REGION" --format='value(status.url)')
```

### (a) Gateway health — liveness 200

```bash
curl -fsS "$GATEWAY_URL/healthz"
# expect: {"status":"ok"}   (HTTP 200)
```

This is the cheap, dependency-free liveness route added in #33 (`GET /healthz` in
`hermes_runtime/gateway_app.py`). A 200 proves the container booted and the ASGI factory
resolved all required secrets (a missing secret fails the boot, not this probe).

### (b) One SMS path — signed inbound webhook 200

Post a correctly **HMAC-SHA256-signed** body to `/webhooks/textline` (signature header
`X-Textline-Signature`, keyed by `TEXTLINE_WEBHOOK_SECRET`, ADR-0021). A normal inbound
fast-acks 200 (ADR-0103); a bad/missing signature returns 401.

```bash
SECRET='<the TEXTLINE_WEBHOOK_SECRET value>'
BODY='{"id":"smoke-1","conversation_id":"conv-smoke","from":"+14165550101","body":"Do you have 225/65R17 in stock?","received_at":"2026-01-01T00:00:00Z","type":"message.created"}'
SIG=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "$SECRET" | sed 's/^.* //')

curl -fsS -X POST "$GATEWAY_URL/webhooks/textline" \
  -H "Content-Type: application/json" \
  -H "X-Textline-Signature: $SIG" \
  --data "$BODY" -o /dev/null -w '%{http_code}\n'
# expect: 200
```

> Use a disposable `conversation_id` in staging. An accepted inbound enqueues a real
> agent turn (which may attempt an outbound reply), so prefer a vendor sandbox / test
> conversation. An opt-out keyword (`STOP`) also returns 200 but sends the fixed
> compliance confirmation instead of starting a turn (ADR-0108).

### (c) Eval quality gate — go-live blocker

The authoritative go-live quality gate is the Slice 29 (issue #31) CI **`text_first_launch`
replay**: a deterministic, no-network/no-LLM replay of recorded transcripts that must
report **`failed_high == 0`** (ADR-0010/0074/0121). It runs in CI (`.github/workflows/ci.yml`,
the `eval-gate` job) and is reproducible locally:

```bash
cd hermes
uv run --frozen python -m eval_runner --suite text_first_launch --harness replay --transcripts-dir ../eval/transcripts
# non-zero exit == high-severity failure == do NOT promote
```

Do not promote a build to production unless this gate is green (`failed_high=0`) on the
commit being deployed.

## Notes

- Per-service independence (separate images, Dockerfiles, and Cloud Run services) is the
  ADR-0098 decision; it preserves independent deploy + scaling for the workbench and gateway.
- No image is built or pushed by this repo's CI; deployment is the manual sequence above.
