# Protected internal agent-turn job route for Cloud Tasks

> **Route names retired (2026-07-21).** The public-ingress example below still says
> `POST /webhooks/textline`; that route is now `/webhooks/simpletexting`. The boundary
> this ADR draws — `/internal/*` is never public ingress — is unchanged.
> Superseding decision → [ADR-0153](0153-provider-neutral-sms-tool-naming.md).

`POST /internal/jobs/agent-turn` is an internal gateway route used by async Textline agent execution per ADR-0105. It must not be exposed as a public customer or employee ingress surface.

## Production authentication

In production, only Google Cloud Tasks may invoke `POST /internal/jobs/agent-turn`.

Cloud Tasks calls the Cloud Run gateway target with an OIDC token. The gateway verifies issuer, audience, and the expected Tasks service account before running job logic. Requests without valid OIDC credentials return `401`.

## Local development authentication

Local `pnpm dev:gateway` may use an in-memory queue instead of Cloud Tasks. In that mode, the same route accepts requests that include a configured `X-Internal-Job-Secret` header matching `services/hermes-gateway/.env.local`.

Local shared-secret auth is for development only and is not used in production.

## Routing boundary

Public ingress remains limited to routes such as:

- `GET /healthz`
- `POST /webhooks/textline`

`/internal/*` routes are not published as public load-balancer entrypoints and are reachable only through Cloud Tasks OIDC calls or local development secret auth.

**Considered options:** shared-secret auth in production (rejected—weaker long-lived credential rotation story); unauthenticated internal routes hidden by URL obscurity (rejected—agent execution and outbound SMS must not be open); run async agent work in the public webhook handler (rejected—conflicts with ADR-0103).
