import { describe, expect, it } from "vitest";
import { SESSION_COOKIE_NAME } from "../auth/session";
import { buildClearedSessionCookie, buildSessionCookie } from "./cookie";

describe("buildSessionCookie", () => {
  it("sets the session cookie with hardening attributes", () => {
    const cookie = buildSessionCookie("tok123", {
      maxAgeSeconds: 3600,
      secure: false,
    });
    expect(cookie).toContain(`${SESSION_COOKIE_NAME}=tok123`);
    expect(cookie).toContain("Path=/");
    expect(cookie).toContain("HttpOnly");
    expect(cookie).toContain("SameSite=Lax");
    expect(cookie).toContain("Max-Age=3600");
    expect(cookie).not.toContain("Secure");
  });

  it("adds Secure when requested", () => {
    const cookie = buildSessionCookie("tok", { maxAgeSeconds: 10, secure: true });
    expect(cookie).toContain("Secure");
  });
});

describe("buildClearedSessionCookie", () => {
  it("expires the cookie immediately", () => {
    const cookie = buildClearedSessionCookie({ secure: false });
    expect(cookie).toContain(`${SESSION_COOKIE_NAME}=;`);
    expect(cookie).toContain("Max-Age=0");
    expect(cookie).toContain("HttpOnly");
  });
});
