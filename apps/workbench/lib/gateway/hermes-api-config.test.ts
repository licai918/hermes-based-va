import { describe, expect, it } from "vitest";
import { resolveProfileApiConfig } from "./hermes-api-config";

describe("resolveProfileApiConfig", () => {
  it("returns config when both the URL and token are present", () => {
    expect(resolveProfileApiConfig("http://copilot.internal", "tok")).toEqual({
      baseUrl: "http://copilot.internal",
      token: "tok",
    });
  });

  it("returns null when either value is missing or empty (in-memory fallback)", () => {
    expect(resolveProfileApiConfig(undefined, "tok")).toBeNull();
    expect(resolveProfileApiConfig("http://copilot.internal", undefined)).toBeNull();
    expect(resolveProfileApiConfig("", "tok")).toBeNull();
    expect(resolveProfileApiConfig("http://copilot.internal", "")).toBeNull();
  });
});
