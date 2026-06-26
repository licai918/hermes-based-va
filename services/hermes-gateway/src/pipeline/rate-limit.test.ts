import { describe, it, expect } from "vitest";
import { createInboundRateLimiter } from "./rate-limit";

describe("createInboundRateLimiter", () => {
  it("allows up to ten messages per sliding minute then soft-limits the eleventh", () => {
    const rl = createInboundRateLimiter();
    const phone = "+15195550100";
    const start = 1_000_000;
    for (let i = 0; i < 10; i++) {
      expect(rl.check(phone, start + i * 1000).allowed).toBe(true);
    }
    const decision = rl.check(phone, start + 10 * 1000);
    expect(decision.allowed).toBe(false);
    expect(decision.count).toBe(10);
  });

  it("tracks senders independently", () => {
    const rl = createInboundRateLimiter();
    for (let i = 0; i < 10; i++) rl.check("+1A", 0);
    expect(rl.check("+1A", 0).allowed).toBe(false);
    expect(rl.check("+1B", 0).allowed).toBe(true);
  });

  it("forgets hits older than the window so the sender recovers", () => {
    const rl = createInboundRateLimiter();
    const phone = "+1C";
    for (let i = 0; i < 10; i++) rl.check(phone, 0);
    expect(rl.check(phone, 50).allowed).toBe(false);
    expect(rl.check(phone, 60_000).allowed).toBe(true);
  });

  it("honors a custom limit and window", () => {
    const rl = createInboundRateLimiter({ limit: 2, windowMs: 1000 });
    expect(rl.check("p", 0).allowed).toBe(true);
    expect(rl.check("p", 100).allowed).toBe(true);
    expect(rl.check("p", 200).allowed).toBe(false);
    expect(rl.check("p", 1001).allowed).toBe(true);
  });
});
