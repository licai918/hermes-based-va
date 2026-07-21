// Canonical inbound event passed from gateway normalization into ingress and
// Hermes runtime code (ADR-0102). Provider-specific field names stay inside the
// gateway's normalize step; agent prompts and tools consume this shape only.
export type ChannelId = "simpletexting_sms";

export type ProviderId = "simpletexting";

export interface InboundChannelEvent {
  /** Fixed `simpletexting_sms` in v1. */
  channel: ChannelId;
  /** Fixed `simpletexting` in v1. */
  provider: ProviderId;
  /** Provider event or message identifier used for idempotency. */
  eventId: string;
  /** Contact-phone conversation identifier (SimpleTexting has no conversation resource). */
  conversationId: string;
  /** Sender phone in normalized E.164 form. */
  fromPhone: string;
  /** Inbound message text. */
  body: string;
  /** Optional inbound media URLs. */
  mediaUrls?: string[];
  /** ISO-8601 receipt timestamp. */
  receivedAt: string;
  /** Original provider event type, retained for audit only. */
  rawEventType: string;
}
