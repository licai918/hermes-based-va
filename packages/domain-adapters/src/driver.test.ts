import { describe, it, expect } from "vitest";
import { resolveIntegrationDriver } from "./driver";

describe("resolveIntegrationDriver", () => {
  it("defaults to mock when the value is undefined", () => {
    expect(resolveIntegrationDriver(undefined)).toBe("mock");
  });

  it("defaults to mock when the value is an empty string", () => {
    expect(resolveIntegrationDriver("")).toBe("mock");
  });

  it("returns the configured driver when recognized", () => {
    expect(resolveIntegrationDriver("mock")).toBe("mock");
    expect(resolveIntegrationDriver("composio")).toBe("composio");
    expect(resolveIntegrationDriver("rest")).toBe("rest");
  });

  it("throws on an unrecognized driver", () => {
    expect(() => resolveIntegrationDriver("sqlite")).toThrow(
      /INTEGRATION_DRIVER/,
    );
  });
});
