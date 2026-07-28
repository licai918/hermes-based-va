import { describe, expect, it } from "vitest";

import { decodeRouteParam } from "./route-param";

describe("decodeRouteParam", () => {
  it("decodes the one layer Next adds, so a real record id survives the round trip", () => {
    // The id of an auto-handled record, as the audit list links to it. The api
    // client encodes again when it builds the BFF URL; without this decode the
    // request went out as `%253A` and the page rendered "Record not found".
    const recordId = "customer_thread:sms:+14165550101";

    expect(decodeRouteParam(encodeURIComponent(recordId))).toBe(recordId);
  });

  it("leaves an id that needs no encoding untouched", () => {
    // Why this went unnoticed: with fixture ids, encoding twice is a no-op, so
    // the bug was invisible until a real conversation existed.
    expect(decodeRouteParam("pac_thread_a")).toBe("pac_thread_a");
  });

  it("returns a malformed segment as-is instead of throwing", () => {
    // decodeURIComponent throws on a lone '%'. A hand-mangled URL should reach
    // the not-found render, not a 500.
    expect(decodeRouteParam("100%")).toBe("100%");
  });
});
