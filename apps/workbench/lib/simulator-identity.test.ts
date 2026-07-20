import { describe, expect, it } from "vitest";
import {
  IDENTITY_PRESETS,
  generateUnknownCallerPhone,
  resolvePresetPhone,
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
