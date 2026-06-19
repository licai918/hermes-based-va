import { describe, it, expect } from "vitest";
import { profileForApiPrefix } from "./routes";
import { HERMES_PROFILES } from "./profiles";

describe("profileForApiPrefix", () => {
  it("maps copilot UI and API paths to the internal copilot profile", () => {
    expect(profileForApiPrefix("/copilot")).toBe(
      HERMES_PROFILES.internalCopilot,
    );
    expect(profileForApiPrefix("/api/copilot/cases")).toBe(
      HERMES_PROFILES.internalCopilot,
    );
  });

  it("maps admin UI and API paths to the supervisor admin profile", () => {
    expect(profileForApiPrefix("/admin/accounts")).toBe(
      HERMES_PROFILES.supervisorAdmin,
    );
    expect(profileForApiPrefix("/api/admin/eval")).toBe(
      HERMES_PROFILES.supervisorAdmin,
    );
  });

  it("returns null for paths with no route-derived profile", () => {
    expect(profileForApiPrefix("/login")).toBeNull();
  });
});
