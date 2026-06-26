# Textline inbound-only webhook normalization to InboundChannelEvent

`services/hermes-gateway` normalizes verified Textline webhooks into a canonical internal event before ingress matching and **External Customer Service Profile** execution.

## v1 accepted event scope

Only inbound customer SMS or MMS message events enter the agent pipeline in v1.

The following event classes return `200` acknowledgment but do not invoke Hermes agent processing:

- outbound message delivery receipts
- echoes of Hermes or employee outbound messages
- unrelated Textline system or administrative events

This keeps the external profile focused on new customer turns rather than provider status noise.

## Canonical payload

Accepted inbound events normalize into `InboundChannelEvent` with at least:

| Field | Purpose |
|-------|---------|
| `channel` | Fixed `textline_sms` in v1 |
| `provider` | Fixed `textline` |
| `eventId` | Provider event or message identifier used for idempotency |
| `conversationId` | Textline conversation identifier |
| `fromPhone` | Sender phone in normalized E.164 form |
| `body` | Inbound message text |
| `mediaUrls` | Optional inbound media URLs |
| `receivedAt` | ISO-8601 receipt timestamp |
| `rawEventType` | Original provider event type for audit only |

`InboundChannelEvent` is defined in `packages/shared` and is the only payload shape passed from gateway normalization into ingress and Hermes runtime code.

Provider-specific field names stay inside `normalize-inbound.ts`. Agent prompts and tools consume the canonical event only.

## Idempotency

The gateway deduplicates on `eventId` before agent execution so Textline webhook retries do not create duplicate agent turns for the same inbound message.

**Considered options:** route every Textline webhook type through the external agent (rejected—delivery receipts and outbound echoes create duplicate or empty turns); enqueue all webhooks before normalization (rejected—adds infrastructure before proven need); pass raw Textline JSON directly into Hermes prompts (rejected—locks agent behavior to provider schema).
