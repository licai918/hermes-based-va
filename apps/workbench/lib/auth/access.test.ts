import { describe, it, expect } from "vitest";
import { HERMES_PROFILES, WORKBENCH_ROLES } from "@toee/shared";
import {
  canAccess,
  profileForApiPrefix,
  requiresSupervisorOrAdmin,
} from "./access";

const { rep, supervisor, admin } = WORKBENCH_ROLES;

describe("canAccess", () => {
  it("allows all roles on non-audit copilot paths", () => {
    for (const role of [rep, supervisor, admin]) {
      expect(canAccess(role, "/copilot")).toBe(true);
      expect(canAccess(role, "/api/copilot/cases")).toBe(true);
    }
  });

  it("allows a rep on the draft-feedback write route (0.0.4 S07, quality-feedback)", () => {
    // Unlike the review write (supervisor/admin-only via the /audit/ prefix),
    // /api/copilot/feedback sits outside /api/copilot/audit/*, so every role
    // reaches it -- reps are the intended authors of draft feedback (see
    // feedback.ts's module docstring).
    expect(canAccess(rep, "/api/copilot/feedback")).toBe(true);
    expect(canAccess(supervisor, "/api/copilot/feedback")).toBe(true);
    expect(canAccess(admin, "/api/copilot/feedback")).toBe(true);
  });

  it("allows every role on the Conversation Simulator (FR-8, 0.0.3 S03)", () => {
    for (const role of [rep, supervisor, admin]) {
      expect(canAccess(role, "/copilot/simulator")).toBe(true);
      expect(canAccess(role, "/api/copilot/simulator/messages")).toBe(true);
      expect(canAccess(role, "/api/copilot/simulator/thread")).toBe(true);
    }
  });

  it("denies reps on audit paths but allows supervisor/admin", () => {
    expect(canAccess(rep, "/copilot/audit/auto-handled")).toBe(false);
    expect(canAccess(rep, "/api/copilot/audit/auto-handled")).toBe(false);
    expect(canAccess(supervisor, "/copilot/audit/auto-handled")).toBe(true);
    expect(canAccess(admin, "/copilot/audit/auto-handled")).toBe(true);
  });

  it("denies reps on the review write route but allows supervisor/admin (0.0.4 S04, quality-feedback)", () => {
    // The interaction-review write's ONLY role boundary: the datastore carries no
    // role column, so this prefix gate is what stands between a rep and a
    // supervisor-only write (see review.ts's module docstring).
    expect(canAccess(rep, "/api/copilot/audit/review")).toBe(false);
    expect(canAccess(supervisor, "/api/copilot/audit/review")).toBe(true);
    expect(canAccess(admin, "/api/copilot/audit/review")).toBe(true);
  });

  it("denies reps on admin paths but allows supervisor/admin", () => {
    expect(canAccess(rep, "/admin/knowledge")).toBe(false);
    expect(canAccess(rep, "/api/admin/accounts")).toBe(false);
    expect(canAccess(supervisor, "/admin/knowledge")).toBe(true);
    expect(canAccess(admin, "/api/admin/accounts")).toBe(true);
  });

  it("gates the integrations page to admin-only, not supervisor (0.0.4 S15, FR-23)", () => {
    // A credential surface: narrower than the rest of /admin/* on purpose.
    expect(canAccess(rep, "/admin/integrations")).toBe(false);
    expect(canAccess(supervisor, "/admin/integrations")).toBe(false);
    expect(canAccess(supervisor, "/api/admin/integrations")).toBe(false);
    expect(canAccess(admin, "/admin/integrations")).toBe(true);
    expect(canAccess(admin, "/api/admin/integrations")).toBe(true);
  });

  it("keeps the S17 reconnect + callback subpaths admin-only (FR-25)", () => {
    // The reconnect/reprobe routes and the externally-reachable OAuth callback all
    // sit under /api/admin/integrations, so they inherit the admin-only gate -- a
    // supervisor cannot start a reconnect or drive the callback.
    for (const path of [
      "/api/admin/integrations/reconnect",
      "/api/admin/integrations/reprobe",
      "/api/admin/integrations/callback",
    ]) {
      expect(canAccess(supervisor, path)).toBe(false);
      expect(canAccess(admin, path)).toBe(true);
    }
  });

  it("allows everyone on ungated paths", () => {
    for (const role of [rep, supervisor, admin]) {
      expect(canAccess(role, "/login")).toBe(true);
      expect(canAccess(role, "/")).toBe(true);
    }
  });
});

describe("requiresSupervisorOrAdmin", () => {
  it("is true for audit and admin paths", () => {
    expect(requiresSupervisorOrAdmin("/copilot/audit/auto-handled")).toBe(true);
    expect(requiresSupervisorOrAdmin("/api/copilot/audit/sales-outreach")).toBe(
      true,
    );
    expect(requiresSupervisorOrAdmin("/admin/knowledge")).toBe(true);
    expect(requiresSupervisorOrAdmin("/api/admin/accounts")).toBe(true);
  });

  it("is false for non-audit copilot and ungated paths", () => {
    expect(requiresSupervisorOrAdmin("/copilot")).toBe(false);
    expect(requiresSupervisorOrAdmin("/api/copilot/cases")).toBe(false);
    expect(requiresSupervisorOrAdmin("/login")).toBe(false);
  });
});

describe("profileForApiPrefix re-export", () => {
  it("matches the shared route-derived profile mapping", () => {
    expect(profileForApiPrefix("/copilot")).toBe(
      HERMES_PROFILES.internalCopilot,
    );
    expect(profileForApiPrefix("/admin/knowledge")).toBe(
      HERMES_PROFILES.supervisorAdmin,
    );
    expect(profileForApiPrefix("/login")).toBeNull();
  });
});
