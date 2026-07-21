import { describe, it, expect } from "vitest";
import { normalizeE164, toInboundChannelEvent } from "./normalize-inbound";

describe("normalizeE164", () => {
  it("passes through a well-formed E.164 number", () => {
    expect(normalizeE164("+15195550123")).toBe("+15195550123");
  });

  it("adds +1 for a bare 10-digit North American number", () => {
    expect(normalizeE164("5195550123")).toBe("+15195550123");
  });

  it("adds + for an 11-digit number that already starts with 1", () => {
    expect(normalizeE164("15195550123")).toBe("+15195550123");
  });

  it("strips spaces, dashes, parentheses, and dots", () => {
    expect(normalizeE164("(519) 555-0123")).toBe("+15195550123");
    expect(normalizeE164("519.555.0123")).toBe("+15195550123");
  });

  it("keeps the leading + for non-NANP international numbers", () => {
    expect(normalizeE164("+44 20 7946 0958")).toBe("+442079460958");
  });
});

describe("toInboundChannelEvent", () => {
  const fields = {
    eventId: "evt_1",
    conversationId: "conv_9",
    fromPhone: "(519) 555-0123",
    body: "where is my order?",
    receivedAt: "2026-06-19T12:00:00.000Z",
    rawEventType: "message:received",
  };

  it("builds the canonical InboundChannelEvent with fixed channel and provider", () => {
    expect(toInboundChannelEvent(fields)).toEqual({
      channel: "simpletexting_sms",
      provider: "simpletexting",
      eventId: "evt_1",
      conversationId: "conv_9",
      fromPhone: "+15195550123",
      body: "where is my order?",
      receivedAt: "2026-06-19T12:00:00.000Z",
      rawEventType: "message:received",
    });
  });

  it("includes mediaUrls only when present and non-empty", () => {
    expect(toInboundChannelEvent({ ...fields, mediaUrls: [] }).mediaUrls).toBeUndefined();
    expect(
      toInboundChannelEvent({ ...fields, mediaUrls: ["https://cdn/x.jpg"] }).mediaUrls
    ).toEqual(["https://cdn/x.jpg"]);
  });
});
