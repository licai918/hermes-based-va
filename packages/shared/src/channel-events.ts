// Canonical inbound event passed from gateway normalization into ingress and
// Hermes runtime code (ADR-0102). Provider-specific field names stay inside the
// gateway's normalize step; agent prompts and tools consume this shape only.
// `textline_sms` is the v1 SMS channel; `simulated_email` is the simulator-driven
// email channel (0.0.3 S17/FR-18, RK-4: no real email provider). Widened
// additively so every existing `textline_sms` round-trip stays byte-compatible.
export type ChannelId = "textline_sms" | "simulated_email";

export type ProviderId = "textline" | "simulated_email";

export interface InboundChannelEvent {
  /** `textline_sms` (SMS) or `simulated_email` (S17). */
  channel: ChannelId;
  /** `textline` (SMS) or `simulated_email` (S17). */
  provider: ProviderId;
  /** Provider event or message identifier used for idempotency. */
  eventId: string;
  /** Textline conversation identifier. */
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
