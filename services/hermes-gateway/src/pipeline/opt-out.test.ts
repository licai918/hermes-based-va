import { describe, it, expect } from "vitest";
import { isOptOutKeyword, SMS_OPT_OUT_CONFIRMATION } from "./opt-out";

describe("isOptOutKeyword", () => {
  it.each(["STOP", "UNSUBSCRIBE", "ARRET"])("detects the bare keyword %s", (keyword) => {
    expect(isOptOutKeyword(keyword)).toBe(true);
  });

  it("is case-insensitive and tolerates surrounding whitespace", () => {
    expect(isOptOutKeyword("  stop  ")).toBe(true);
    expect(isOptOutKeyword("Stop")).toBe(true);
  });

  it("detects a keyword used as a standalone word in a sentence", () => {
    expect(isOptOutKeyword("Please STOP texting me")).toBe(true);
    expect(isOptOutKeyword("unsubscribe please")).toBe(true);
  });

  it("does not match keywords embedded inside other words", () => {
    expect(isOptOutKeyword("nonstop service")).toBe(false);
    expect(isOptOutKeyword("arretez vous")).toBe(false);
  });

  it("returns false for unrelated or empty messages", () => {
    expect(isOptOutKeyword("where is my order?")).toBe(false);
    expect(isOptOutKeyword("")).toBe(false);
  });
});

describe("SMS_OPT_OUT_CONFIRMATION", () => {
  it("is the fixed brief English confirmation from ADR-0016", () => {
    expect(SMS_OPT_OUT_CONFIRMATION).toBe(
      "You have been unsubscribed from marketing messages. You can still text us for account support."
    );
  });
});
