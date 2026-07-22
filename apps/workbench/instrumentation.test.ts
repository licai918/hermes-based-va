import { describe, expect, it } from "vitest";
import { register } from "./instrumentation";

// 0.0.4 S09 acceptance ① calls for a boot-time fail-closed test; before this file
// `instrumentation.ts` had zero automated coverage (its five sibling tests, in
// hermes-api-config.test.ts, only cover the pure config functions it calls). The
// two early-returns below are exactly where a silent downgrade could reappear
// unnoticed, so each gets its own case (0.0.4 S09 fix wave 1, finding 2).
const FULL = {
  HERMES_COPILOT_API_URL: "http://copilot.internal",
  HERMES_COPILOT_API_TOKEN: "copilot-tok",
  HERMES_ADMIN_API_URL: "http://admin.internal",
  HERMES_ADMIN_API_TOKEN: "admin-tok",
};

describe("register (Next.js instrumentation boot hook)", () => {
  it("throws naming the missing variables in the nodejs runtime with no config", async () => {
    await expect(register({ NEXT_RUNTIME: "nodejs" })).rejects.toThrow(
      /HERMES_COPILOT_API_URL.*HERMES_COPILOT_API_TOKEN.*HERMES_ADMIN_API_URL.*HERMES_ADMIN_API_TOKEN/s,
    );
  });

  it("does not throw in the nodejs runtime once fully configured", async () => {
    await expect(register({ NEXT_RUNTIME: "nodejs", ...FULL })).resolves.toBeUndefined();
  });

  it("does NOT throw outside the nodejs runtime (edge/middleware), even unconfigured", async () => {
    // The edge runtime never talks to the Hermes API -- this skip is deliberate,
    // not a gap, and must stay silent regardless of configuration.
    await expect(register({ NEXT_RUNTIME: "edge" })).resolves.toBeUndefined();
  });

  it("does NOT throw during `next build` (phase-production-build), even unconfigured", async () => {
    // Deliberate and adjudicated (S09 report §11): backend URLs/tokens are runtime
    // config, and requiring them at build time would bake credentials into the
    // image. This asserts the skip is intentional, not that it should change.
    await expect(
      register({ NEXT_RUNTIME: "nodejs", NEXT_PHASE: "phase-production-build" }),
    ).resolves.toBeUndefined();
  });
});
