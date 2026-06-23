import { DEV_SESSION_SECRET, resolveSessionSecret } from "./session-secret";

describe("resolveSessionSecret", () => {
  it("returns the configured env secret when present", () => {
    expect(resolveSessionSecret("prod-secret-value")).toBe("prod-secret-value");
  });

  it("falls back to the dev secret when undefined or empty", () => {
    expect(resolveSessionSecret(undefined)).toBe(DEV_SESSION_SECRET);
    expect(resolveSessionSecret("")).toBe(DEV_SESSION_SECRET);
  });
});
