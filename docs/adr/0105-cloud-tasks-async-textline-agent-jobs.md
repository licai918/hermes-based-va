# Cloud Tasks handoff for async Textline agent execution

> **Two independent supersessions — both apply.** This ADR's *provider* and its
> *transport* were each replaced, on separate branches, within a day of each
> other.
>
> **1. Provider retired (2026-07-21).** Textline was cancelled: the webhook is
> `/webhooks/simpletexting` and outbound SMS uses `toee_sms_reply`.
> Superseding decision → [ADR-0153](0153-provider-neutral-sms-tool-naming.md).
>
> **2. Transport superseded (0.0.4).** Cloud Tasks was never built and
> contradicts the local-first posture of ADR-0142; the async handoff is a durable
> **Postgres job queue** in the Toee Business Datastore
> ([migration 0014](../../hermes-runtime/migrations/0014_job_queue.sql)), claimed
> by worker processes with `FOR UPDATE SKIP LOCKED`. What changes is the transport
> and the handler seam: a turn worker claims from the table instead of Cloud Tasks
> POSTing `/internal/jobs/agent-turn`.
> Superseding decision → [ADR-0155](0155-durable-postgres-job-queue-supersedes-cloud-tasks.md).
>
> **What still holds:** the **enqueue rule below** — identity keys only
> (`eventId` + `conversationId`), no PII body — and reload-by-`eventId`
> (ADR-0107). Nothing else in this ADR is live: read the body as the historical
> record of a decision whose provider *and* transport have both moved on.

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
