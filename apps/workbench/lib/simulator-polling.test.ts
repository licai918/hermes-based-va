import { describe, expect, it } from "vitest";
import type { ThreadMessage } from "./gateway/types";
import { countOutbound, hasNewOutboundReply } from "./simulator-polling";

function msg(overrides: Partial<ThreadMessage> = {}): ThreadMessage {
  return {
    messageId: "m1",
    threadId: "t1",
    at: 0,
    author: "customer",
    channel: "sms",
    body: "hi",
    autoHandled: false,
    activeCaseSegment: true,
    ...overrides,
  };
}

describe("countOutbound", () => {
  it("counts only hermes-authored turns", () => {
    const messages = [
      msg({ messageId: "1", author: "customer" }),
      msg({ messageId: "2", author: "hermes" }),
      msg({ messageId: "3", author: "workbench" }),
      msg({ messageId: "4", author: "hermes" }),
    ];
    expect(countOutbound(messages)).toBe(2);
  });
});

describe("hasNewOutboundReply", () => {
  it("is false when the outbound count is unchanged", () => {
    const before = [msg({ messageId: "1", author: "customer" })];
    const after = [msg({ messageId: "1", author: "customer" })];
    expect(hasNewOutboundReply(before, after)).toBe(false);
  });

  it("is true once a new hermes turn appears", () => {
    const before = [msg({ messageId: "1", author: "customer" })];
    const after = [
      msg({ messageId: "1", author: "customer" }),
      msg({ messageId: "2", author: "hermes" }),
    ];
    expect(hasNewOutboundReply(before, after)).toBe(true);
  });

  it("is false if the new turn is from the customer, not hermes", () => {
    const before = [msg({ messageId: "1", author: "customer" })];
    const after = [
      msg({ messageId: "1", author: "customer" }),
      msg({ messageId: "2", author: "customer" }),
    ];
    expect(hasNewOutboundReply(before, after)).toBe(false);
  });
});
