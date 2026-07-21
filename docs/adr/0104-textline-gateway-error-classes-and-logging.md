# Textline gateway error classes, logging, and case creation boundaries

> **Substrate and service framing superseded (ADR-0140/0142, ADR-0139).** The error
> classes, HTTP codes, case-creation boundaries, and retry semantics all still hold.
> Superseded: the Persist stage targets the **Toee Business Datastore** (Postgres), not
> **Hermes Native Memory**; and the Node `services/hermes-gateway` framing — the
> gateway is the Python FastAPI `hermes-runtime/`.
> Current direction → [`docs/architecture/memory-layers.md`](../architecture/memory-layers.md).

`services/hermes-gateway` classifies Textline webhook failures by pipeline stage and separates provider retry behavior from **Follow-up Case** creation.

## Pre-acknowledgment stages

| Stage | Condition | HTTP | Create case | Provider retry |
|-------|-----------|------|-------------|----------------|
| Verify | Invalid signature or token | `401` | No | Yes |
| Normalize | Non-inbound customer event | `200` | No | No |
| Idempotency | Duplicate `eventId` already processed | `200` | No | No |
| Ingress | `match_phone` transient timeout or `5xx` | `500` | No | Yes |
| Ingress | No match or ambiguous match resolved to snapshot | `200` | No | No |
| Persist | **Hermes Native Memory** transient write failure | `500` | No | Yes |

Ingress business outcomes such as **Unmatched Caller** or **Ambiguous Phone Match** are normal states, not gateway errors. They still return `200` after the inbound turn is durably recorded.

## Post-acknowledgment async stage

After `200`, asynchronous **External Customer Service Profile** execution follows ADR-0103.

| Stage | Condition | HTTP already sent | Create case | Provider retry |
|-------|-----------|-------------------|-------------|----------------|
| Agent | Business tool timeout or retryable `5xx` per ADR-0020 | `200` | Yes, `tool_unavailable` | No |
| Agent | Unhandled async processing failure | `200` | Yes, standard follow-up | No |

Pre-ack ingress or persistence failures do not create **Follow-up Case** records because the customer has not yet entered a completed inbound-and-agent workflow turn.

## Structured logging

Gateway logs use structured fields at every failure:

- `eventId`
- `conversationId`
- `fromPhone`
- `stage` — `verify`, `normalize`, `ingress`, `persist`, or `agent`
- `errorClass`
- `retryable`

Pre-ack failures are logged as errors and do not enter agent prompts. Async agent failures are logged as errors and recorded in audit and case evidence.

**Considered options:** create cases for ingress transient failures (rejected—duplicate and empty cases on provider retries); return `200` for all failures to stop retries (rejected—loses recovery for persistence and ingress outages); retry async agent failures through Textline webhook redelivery (rejected—inbound event was already acknowledged).
