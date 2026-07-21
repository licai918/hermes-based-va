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

  it("denies reps on admin paths but allows supervisor/admin", () => {
    expect(canAccess(rep, "/admin/knowledge")).toBe(false);
    expect(canAccess(rep, "/api/admin/accounts")).toBe(false);
    expect(canAccess(supervisor, "/admin/knowledge")).toBe(true);
    expect(canAccess(admin, "/api/admin/accounts")).toBe(true);
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
