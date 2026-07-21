# Cloud Tasks handoff for async Textline agent execution

> **Transport superseded by ADR-0153.** Cloud Tasks was never built and
> contradicts the local-first posture of ADR-0142; the async handoff is a durable
> **Postgres job queue** in the Toee Business Datastore
> ([migration 0011](../../hermes-runtime/migrations/0011_job_queue.sql)), claimed
> by worker processes with `FOR UPDATE SKIP LOCKED`. The **enqueue rule below
> still holds** — identity keys only (`eventId` + `conversationId`), no PII body —
> as does reload-by-`eventId` (ADR-0107). What changes is the transport and the
> handler seam: a turn worker claims from the table instead of Cloud Tasks POSTing
> `/internal/jobs/agent-turn`.

After a Textline webhook returns `200`, **External Customer Service Profile** execution runs asynchronously through Google Cloud Tasks rather than inside the webhook request lifecycle.

Cloud Tasks is the first queue-style Google Cloud service activated for **Hermes VA** because fast webhook acknowledgment in ADR-0103 requires durable post-ack work handoff on Cloud Run.

## Enqueue rule

Once verification, normalization, ingress matching, inbound persistence, and idempotency checks succeed, the gateway enqueues a task containing at minimum:

- `eventId`
- `conversationId`

The webhook handler does not wait for model inference, business-tool calls, or Textline outbound delivery.

## Job handler route

`services/hermes-gateway` exposes a protected internal route:

- `POST /internal/jobs/agent-turn`

The handler:

1. reloads the persisted inbound turn by `eventId`
2. re-checks idempotency for agent execution when needed
3. runs the **External Customer Service Profile**
4. sends outbound SMS through `toee_textline_reply` when appropriate

Async failures follow ADR-0104 and ADR-0020. They do not change the webhook response status.

## Local development

`pnpm dev:gateway` may use an in-memory queue that mimics Cloud Tasks enqueue and delivery. Production uses Cloud Tasks only.

**Considered options:** fire-and-forget processing in the same Cloud Run request after `200` (rejected—unreliable once the response completes); Pub/Sub push for v1 (rejected—extra operational surface before proven need); rely on Textline webhook retries to replay agent work (rejected—inbound events are already acknowledged).
