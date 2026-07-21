import { describe, it, expect } from "vitest";
import {
  isToolAction,
  type InboundChannelEvent,
  type SessionIdentitySnapshot,
} from "@toee/shared";

describe("shared contracts consumed by domain-adapters", () => {
  it("exposes the v1 tool catalog across the workspace boundary", () => {
    expect(isToolAction("toee_sms_reply", "send_message")).toBe(true);
  });

  it("types an InboundChannelEvent and a SessionIdentitySnapshot", () => {
    const event: InboundChannelEvent = {
      channel: "simpletexting_sms",
      provider: "simpletexting",
      eventId: "evt_1",
      conversationId: "conv_1",
      fromPhone: "+14165550111",
      body: "hello",
      receivedAt: "2026-01-01T00:00:00Z",
      rawEventType: "message.created",
    };
    const snapshot: SessionIdentitySnapshot = {
      outcome: "verified_customer",
      shopifyCustomerId: "gid://shopify/Customer/1001",
      resolvedAt: "2026-01-01T00:00:00Z",
    };

    expect(event.channel).toBe("simpletexting_sms");
    expect(snapshot.outcome).toBe("verified_customer");
  });
});
