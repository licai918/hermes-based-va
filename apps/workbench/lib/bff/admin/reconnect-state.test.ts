import { describe, expect, it } from "vitest";
import {
  clearedReconnectStateCookie,
  newReconnectState,
  reconnectStateCookie,
  reconnectStateMatches,
  RECONNECT_STATE_COOKIE,
} from "./reconnect-state";

// The OAuth reconnect callback is externally reachable; its only defense against a
// forged callback is that the round-tripped `state` must exactly match the httpOnly
// cookie set at initiation. These pin the fail-closed comparison (FR-25).
describe("reconnect state binding (FR-25)", () => {
  it("mints a non-empty, unique state each time", () => {
    const a = newReconnectState();
    const b = newReconnectState();
    expect(a).toBeTruthy();
    expect(a).not.toBe(b);
  });

  it("accepts ONLY an exact cookie==query match", () => {
    expect(reconnectStateMatches("abc", "abc")).toBe(true);
  });

  it("refuses a mismatch, a missing cookie, or a missing query value (fail closed)", () => {
    expect(reconnectStateMatches("abc", "xyz")).toBe(false);
    expect(reconnectStateMatches(undefined, "abc")).toBe(false);
    expect(reconnectStateMatches("abc", null)).toBe(false);
    expect(reconnectStateMatches("", "")).toBe(false);
    expect(reconnectStateMatches(undefined, null)).toBe(false);
  });

  it("sets an httpOnly, sameSite=lax, scoped cookie (survives the provider redirect)", () => {
    const c = reconnectStateCookie("s1", true);
    expect(c.name).toBe(RECONNECT_STATE_COOKIE);
    expect(c.value).toBe("s1");
    expect(c.httpOnly).toBe(true);
    // lax (not strict) so the cookie rides the top-level GET redirect back from the
    // provider; httpOnly so page JS cannot read or forge it.
    expect(c.sameSite).toBe("lax");
    expect(c.path).toBe("/api/admin/integrations");
    expect(c.secure).toBe(true);
    expect(c.maxAge).toBeGreaterThan(0);
  });

  it("clears the one-time cookie with maxAge 0", () => {
    expect(clearedReconnectStateCookie(false).maxAge).toBe(0);
  });
});
