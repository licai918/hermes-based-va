import { describe, it, expect } from "vitest";
import { WORKBENCH_ROLES, type WorkbenchRoleId } from "@toee/shared";
import {
  createSessionToken,
  isSessionExpired,
  SESSION_COOKIE_NAME,
  SESSION_IDLE_MS,
  verifySessionToken,
  type WorkbenchSession,
} from "./session";

const SECRET = "test-secret-value";

function sampleSession(
  overrides: Partial<WorkbenchSession> = {},
): WorkbenchSession {
  return {
    accountId: "acc-1",
    username: "rep",
    role: WORKBENCH_ROLES.rep,
    lastActivityAt: 1_700_000_000_000,
    ...overrides,
  };
}

describe("session constants", () => {
  it("exposes the cookie name and 8h idle window", () => {
    expect(SESSION_COOKIE_NAME).toBe("workbench_session");
    expect(SESSION_IDLE_MS).toBe(8 * 60 * 60 * 1000);
  });
});

describe("createSessionToken / verifySessionToken", () => {
  it("round-trips and returns the payload", async () => {
    const session = sampleSession();
    const token = await createSessionToken(session, SECRET);
    expect(token).toContain(".");
    expect(await verifySessionToken(token, SECRET)).toEqual(session);
  });

  it("returns null for a tampered payload", async () => {
    const token = await createSessionToken(sampleSession(), SECRET);
    const [payload, sig] = token.split(".");
    const flipped = (payload![0] === "A" ? "B" : "A") + payload!.slice(1);
    expect(await verifySessionToken(`${flipped}.${sig}`, SECRET)).toBeNull();
  });

  it("returns null for the wrong secret", async () => {
    const token = await createSessionToken(sampleSession(), SECRET);
    expect(await verifySessionToken(token, "different-secret")).toBeNull();
  });

  it("returns null for a malformed token", async () => {
    expect(await verifySessionToken("not-a-token", SECRET)).toBeNull();
    expect(await verifySessionToken("", SECRET)).toBeNull();
    expect(await verifySessionToken("a.b.c", SECRET)).toBeNull();
  });

  it("returns null when role is not a known workbench role", async () => {
    const badToken = await createSessionToken(
      { ...sampleSession(), role: "root" as WorkbenchRoleId },
      SECRET,
    );
    expect(await verifySessionToken(badToken, SECRET)).toBeNull();
  });

  it("returns null when the payload shape is invalid", async () => {
    const token = await createSessionToken(
      { accountId: "a" } as unknown as WorkbenchSession,
      SECRET,
    );
    expect(await verifySessionToken(token, SECRET)).toBeNull();
  });
});

describe("isSessionExpired", () => {
  it("is false at the idle boundary and true just past it", () => {
    const session = sampleSession({ lastActivityAt: 1000 });
    expect(isSessionExpired(session, 1000 + SESSION_IDLE_MS)).toBe(false);
    expect(isSessionExpired(session, 1000 + SESSION_IDLE_MS + 1)).toBe(true);
  });
});
