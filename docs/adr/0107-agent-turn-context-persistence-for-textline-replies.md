# AgentTurnContext persistence for async Textline reply binding

> **Storage substrate superseded by ADR-0140/0142.** Persist-before-ack, the minimal
> Cloud Tasks payload, reload-by-`eventId`, and reply-binding enforcement all still hold.
> Superseded: the storage substrate — **AgentTurnContext** persists to the **Toee Business
> Datastore** (Postgres, L2), not **Hermes Native Memory**. "Memory is the source of
> truth" under **Async job behavior** now inverts current truth: the datastore is the
> source of truth, and Hermes memory is conversation-only.
> Current direction → [`docs/architecture/memory-layers.md`](../architecture/memory-layers.md).

> **Provider retired (2026-07-21).** The channel literals, the persisted thread key, and
> the reply tool are provider-neutral now (`toee_sms_reply`); the binding rule stands.
> Superseding decision → [ADR-0153](0153-provider-neutral-sms-tool-naming.md).

When the Textline gateway durably records an accepted inbound turn before webhook acknowledgment, it stores an **AgentTurnContext** in **Hermes Native Memory**.

Cloud Tasks payloads stay minimal and carry at minimum `eventId` and `conversationId`. The async job reloads the full turn context from memory by `eventId`.

## AgentTurnContext fields

Each persisted inbound turn stores at least:

| Field | Purpose |
|-------|---------|
| `eventId` | Provider idempotency key |
| `conversationId` | Textline conversation identifier |
| `smsSessionId` | Active **SMS Session** bound at ingress |
| `customerThreadId` | Long-lived **Customer Thread** identifier |
| `fromPhone` | Normalized sender phone |
| `sessionIdentitySnapshot` | **Session Identity Snapshot** written during **Ingress Phone Match** |
| `inboundBodyRef` | Reference to the persisted inbound message body |

## Async job behavior

`POST /internal/jobs/agent-turn` loads `AgentTurnContext` by `eventId` and verifies that any supplied `conversationId` matches the stored record.

The **External Customer Service Profile** runs with that loaded session context only. `toee_textline_reply.send_message` must use the loaded `smsSessionId` and `conversationId`. **Tool Gate** rejects outbound sends that do not match the inbound turn binding.

The job payload does not carry the full inbound message body or snapshot as authoritative state. Memory is the source of truth.

**Considered options:** pass full inbound payload through Cloud Tasks (rejected—duplicate PII and stale task data); resolve session only from `conversationId` at job time without the ingress snapshot (rejected—weak reply authorization); allow reply tools to target a phone number supplied in model output (rejected—conflicts with ADR-0066).
