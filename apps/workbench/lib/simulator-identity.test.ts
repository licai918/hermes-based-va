import { describe, expect, it } from "vitest";
import {
  EMAIL_PRESETS,
  IDENTITY_PRESETS,
  SEEDED_VERIFIED_PHONE,
  generateUnknownCallerEmail,
  generateUnknownCallerPhone,
  resolvePresetEmail,
  resolvePresetPhone,
  resolveVerifiedPhone,
} from "./simulator-identity";

describe("generateUnknownCallerPhone", () => {
  it("produces a +1555 number shape", () => {
    const phone = generateUnknownCallerPhone();
    expect(phone).toMatch(/^\+1555\d{7}$/);
  });

  it("is deterministic given a fixed random source", () => {
    const fixed = () => 0.5;
    expect(generateUnknownCallerPhone(fixed)).toBe(generateUnknownCallerPhone(fixed));
  });

  it("regenerates a different number on the next call (uniqueness shape)", () => {
    let n = 0;
    const sequence = () => {
      n += 1;
      return n % 2 === 0 ? 0.1 : 0.9;
    };
    const first = generateUnknownCallerPhone(sequence);
    const second = generateUnknownCallerPhone(sequence);
    expect(first).not.toBe(second);
  });
});

describe("resolvePresetPhone", () => {
  it("resolves the verified preset to the seeded mock-driver verified number", () => {
    expect(resolvePresetPhone("verified")).toBe("+14165550101");
  });

  it("resolves the ambiguous preset to the seeded mock-driver ambiguous number", () => {
    expect(resolvePresetPhone("ambiguous")).toBe("+14165550222");
  });

  it("resolves the unknown preset to a freshly generated number", () => {
    const phone = resolvePresetPhone("unknown", () => 0.42);
    expect(phone).toMatch(/^\+1555\d{7}$/);
  });
});

describe("IDENTITY_PRESETS", () => {
  it("declares exactly the three FR-9 presets", () => {
    expect(IDENTITY_PRESETS.map((p) => p.id)).toEqual(["verified", "ambiguous", "unknown"]);
  });
});

// PAC-6 (0.0.4 S12): under INTEGRATION_DRIVER=composio the seeded mock number is
// nobody in the live Shopify store, so the verified preset points at a dedicated
// live TEST CUSTOMER instead -- never a real customer's number.
describe("resolveVerifiedPhone", () => {
  it("falls back to the seeded mock number when unconfigured", () => {
    expect(resolveVerifiedPhone(undefined)).toBe(SEEDED_VERIFIED_PHONE);
    expect(resolveVerifiedPhone("")).toBe(SEEDED_VERIFIED_PHONE);
    expect(resolveVerifiedPhone("   ")).toBe(SEEDED_VERIFIED_PHONE);
  });

  it("uses the configured live test-customer phone when set", () => {
    expect(resolveVerifiedPhone(" +16475550199 ")).toBe("+16475550199");
  });
});

// S18/FR-11: email identity presets, seeded from the same mock identity
// driver's email_matches table (hermes/toee_hermes/drivers/mock/identity.py).
describe("generateUnknownCallerEmail", () => {
  it("produces a simulated (never-real) address shape", () => {
    const email = generateUnknownCallerEmail();
    expect(email).toMatch(/^unknown-\d{7}@sim\.example$/);
  });

  it("is deterministic given a fixed random source", () => {
    const fixed = () => 0.5;
    expect(generateUnknownCallerEmail(fixed)).toBe(generateUnknownCallerEmail(fixed));
  });

  it("regenerates a different address on the next call (uniqueness shape)", () => {
    let n = 0;
    const sequence = () => {
      n += 1;
      return n % 2 === 0 ? 0.1 : 0.9;
    };
    const first = generateUnknownCallerEmail(sequence);
    const second = generateUnknownCallerEmail(sequence);
    expect(first).not.toBe(second);
  });
});

describe("resolvePresetEmail", () => {
  it("resolves the verified preset to the seeded mock-driver verified address", () => {
    expect(resolvePresetEmail("verified")).toBe("accounts@acme-fleet.example");
  });

  it("resolves the ambiguous preset to the seeded mock-driver ambiguous address", () => {
    expect(resolvePresetEmail("ambiguous")).toBe("shared-inbox@acme-fleet.example");
  });

  it("resolves the unknown preset to a freshly generated simulated address", () => {
    const email = resolvePresetEmail("unknown", () => 0.42);
    expect(email).toMatch(/^unknown-\d{7}@sim\.example$/);
  });
});

describe("EMAIL_PRESETS", () => {
  it("declares exactly the three FR-11 presets", () => {
    expect(EMAIL_PRESETS.map((p) => p.id)).toEqual(["verified", "ambiguous", "unknown"]);
  });
});
