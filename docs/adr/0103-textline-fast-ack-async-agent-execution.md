# Fast Textline webhook acknowledgment with async external agent execution

> **Storage substrate superseded by ADR-0140/0142.** The entire fast-ack/async pipeline
> and its step ordering still hold. Only step 5's target changes: the inbound turn
> persists to the **Toee Business Datastore** (Postgres, L2), not **Hermes Native
> Memory**, which is conversation-only.
> Current direction → [`docs/architecture/memory-layers.md`](../architecture/memory-layers.md).

`POST /webhooks/textline` separates webhook acknowledgment from external agent execution so Textline retries do not duplicate customer turns or stall on long model and tool work.

## Synchronous pre-ack pipeline

Before returning `200`, the gateway completes these steps in order:

1. verify Textline webhook authenticity per ADR-0021
2. normalize an accepted inbound customer event into `InboundChannelEvent` per ADR-0102
3. deduplicate on `eventId`
4. run **Ingress Phone Match** and write the current **Session Identity Snapshot** per ADR-0043
5. persist the inbound turn to **Hermes Native Memory**

If signature verification fails, the gateway returns `401` and does not persist or enqueue work.

If normalization, ingress matching, or inbound persistence fails with a retryable gateway error, the gateway returns `500` so Textline may retry.

If `eventId` was already processed successfully, the gateway returns `200` without starting a second agent run.

## Async post-ack execution

After a successful `200`, the gateway schedules asynchronous execution of the **External Customer Service Profile** for that persisted inbound turn. Outbound SMS uses `toee_textline_reply` inside that async run.

The webhook response does not wait for model inference, business-tool calls, or Textline outbound delivery to finish.

Async agent failures do not change the webhook status once the inbound turn was durably recorded. Failures follow **Follow-up Case**, audit, and tool-failure rules instead of causing Textline to retry the same inbound event.

**Considered options:** return `200` only after the full agent turn and outbound send complete (rejected—webhook timeout and duplicate retry risk); acknowledge before verification or persistence (rejected—loses durable ingress state and weak auditability); use non-`200` responses for async agent failures after ack (rejected—creates duplicate inbound processing on provider retries).
