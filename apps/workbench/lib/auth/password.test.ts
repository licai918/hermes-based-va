import { describe, it, expect } from "vitest";
import { hashPassword, validatePassword, verifyPassword } from "./password";

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

describe("hashPassword / verifyPassword", () => {
  it("round-trips: verify is true for the correct password", () => {
    const stored = hashPassword("Workbench123!");
    expect(verifyPassword("Workbench123!", stored)).toBe(true);
  });

  it("is false for the wrong password", () => {
    const stored = hashPassword("Workbench123!");
    expect(verifyPassword("WrongPassword9", stored)).toBe(false);
  });

  it("returns false (never throws) for malformed stored strings", () => {
    expect(verifyPassword("x", "not-a-valid-hash")).toBe(false);
    expect(verifyPassword("x", "")).toBe(false);
    expect(verifyPassword("x", "scrypt$onlytwo")).toBe(false);
    expect(verifyPassword("x", "bcrypt$aa$bb")).toBe(false);
    expect(verifyPassword("x", "scrypt$zz$zz")).toBe(false);
  });

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
