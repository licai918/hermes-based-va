import type { InboundChannelEvent } from "@toee/shared";

// Canonical inbound normalization for the SMS pipeline (ADR-0102). The
// provider-specific JSON shape and accepted/ignored event classification are
// extracted by the route layer (issue #17) once the provider webhook schema is
// confirmed; this module owns the schema-independent canonical pieces: E.164
// phone normalization and building the InboundChannelEvent the rest of the
// system consumes.

/** Extracted inbound SMS fields, provider key names already resolved. */
export interface SmsInboundFields {
  eventId: string;
  conversationId: string;
  fromPhone: string;
  body: string;
  receivedAt: string;
  rawEventType: string;
  mediaUrls?: string[];
}

// Normalize a phone string to E.164. A leading + is treated as authoritative
// (international); otherwise a bare 10-digit number is assumed North American
// (+1) and an 11-digit 1-prefixed number is promoted to +1...
export function normalizeE164(input: string): string {
  const trimmed = input.trim();
  const hasPlus = trimmed.startsWith("+");
  const digits = trimmed.replace(/\D/g, "");
  if (hasPlus) {
    return `+${digits}`;
  }
  if (digits.length === 10) {
    return `+1${digits}`;
  }
  if (digits.length === 11 && digits.startsWith("1")) {
    return `+${digits}`;
  }
  return `+${digits}`;
}

export function toInboundChannelEvent(fields: SmsInboundFields): InboundChannelEvent {
  const event: InboundChannelEvent = {
    channel: "simpletexting_sms",
    provider: "simpletexting",
    eventId: fields.eventId,
    conversationId: fields.conversationId,
    fromPhone: normalizeE164(fields.fromPhone),
    body: fields.body,
    receivedAt: fields.receivedAt,
    rawEventType: fields.rawEventType,
  };
  if (fields.mediaUrls && fields.mediaUrls.length > 0) {
    event.mediaUrls = fields.mediaUrls;
  }
  return event;
}
