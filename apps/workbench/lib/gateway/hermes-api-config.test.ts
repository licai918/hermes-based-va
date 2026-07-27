import { describe, expect, it } from "vitest";
import {
  assertHermesApiConfig,
  requireProfileApiConfig,
} from "./hermes-api-config";

const FULL = {
  HERMES_COPILOT_API_URL: "http://copilot.internal",
  HERMES_COPILOT_API_TOKEN: "copilot-tok",
  HERMES_ADMIN_API_URL: "http://admin.internal",
  HERMES_ADMIN_API_TOKEN: "admin-tok",
};

describe("requireProfileApiConfig", () => {
  it("returns the per-profile base URL + token", () => {
    expect(requireProfileApiConfig("copilot", FULL)).toEqual({
      baseUrl: "http://copilot.internal",
      token: "copilot-tok",
    });
    expect(requireProfileApiConfig("admin", FULL)).toEqual({
      baseUrl: "http://admin.internal",
      token: "admin-tok",
    });
  });

  it("throws naming the missing variable instead of degrading to a fallback", () => {
    expect(() =>
      requireProfileApiConfig("copilot", { ...FULL, HERMES_COPILOT_API_TOKEN: "" }),
    ).toThrow(/HERMES_COPILOT_API_TOKEN/);
    expect(() =>
      requireProfileApiConfig("admin", { ...FULL, HERMES_ADMIN_API_URL: undefined }),
    ).toThrow(/HERMES_ADMIN_API_URL/);
  });
});

describe("assertHermesApiConfig (boot gate, FR-3)", () => {
  it("passes when both profiles are configured", () => {
    expect(() => assertHermesApiConfig(FULL)).not.toThrow();
  });

  it("names EVERY missing variable in one message", () => {
    let message = "";
    try {
      assertHermesApiConfig({
        HERMES_COPILOT_API_URL: "http://copilot.internal",
        HERMES_COPILOT_API_TOKEN: "",
      });
    } catch (err) {
      message = (err as Error).message;
    }
    expect(message).toContain("HERMES_COPILOT_API_TOKEN");
    expect(message).toContain("HERMES_ADMIN_API_URL");
    expect(message).toContain("HERMES_ADMIN_API_TOKEN");
    // The configured one is not reported as missing.
    expect(message).not.toContain("HERMES_COPILOT_API_URL");
  });

  it("says there is no fallback, so the failure is not read as a warning", () => {
    expect(() => assertHermesApiConfig({})).toThrow(/no in-memory fallback/);
  });
});
