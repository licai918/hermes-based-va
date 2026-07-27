import { describe, it, expect } from "vitest";
import { hashPassword, validatePassword } from "./password";

describe("validatePassword", () => {
  it("rejects passwords shorter than 12 characters", () => {
    const result = validatePassword("Ab1aaaa");
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.errors.some((e) => e.includes("12"))).toBe(true);
    }
  });

  it("requires at least one uppercase letter", () => {
    const result = validatePassword("abcdefghij12");
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.errors.some((e) => /uppercase/i.test(e))).toBe(true);
    }
  });

  it("requires at least one lowercase letter", () => {
    const result = validatePassword("ABCDEFGHIJ12");
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.errors.some((e) => /lowercase/i.test(e))).toBe(true);
    }
  });

  it("requires at least one digit", () => {
    const result = validatePassword("Abcdefghijkl");
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.errors.some((e) => /digit/i.test(e))).toBe(true);
    }
  });

  it("accepts a valid password", () => {
    expect(validatePassword("Workbench123!")).toEqual({ ok: true });
    expect(validatePassword("Abcdefghij12")).toEqual({ ok: true });
  });
});

// 0.0.4 S09: verification moved to toee_workbench_admin.authenticate, so the only
// thing left to pin here is that admin-created accounts are hashed in the format
// the Python side parses (ADR-0144; hermes-runtime's TS_GENERATED_HASH test is the
// other half of that contract).
describe("hashPassword", () => {
  it("uses a random salt so two hashes of the same password differ", () => {
    expect(hashPassword("Workbench123!")).not.toBe(hashPassword("Workbench123!"));
  });

  it("formats the stored hash as scrypt$<saltHex>$<hashHex>", () => {
    const parts = hashPassword("Workbench123!").split("$");
    expect(parts.length).toBe(3);
    expect(parts[0]).toBe("scrypt");
    expect(parts[1]).toMatch(/^[0-9a-f]{32}$/);
    expect(parts[2]).toMatch(/^[0-9a-f]+$/);
  });
});
