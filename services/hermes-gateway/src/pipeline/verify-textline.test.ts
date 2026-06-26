import { describe, it, expect } from "vitest";
import { createHmac } from "node:crypto";
import { verifyTextlineSignature } from "./verify-textline";

const secret = "whsec_textline_test";

function sign(body: string, key = secret): string {
  return createHmac("sha256", key).update(body, "utf8").digest("hex");
}

describe("verifyTextlineSignature", () => {
  it("accepts a signature computed with the shared secret over the raw body", () => {
    const rawBody = JSON.stringify({ event: "message:received", id: "evt_1" });
    expect(
      verifyTextlineSignature({ rawBody, signature: sign(rawBody), secret })
    ).toBe(true);
  });

  it("rejects a signature produced with a different secret", () => {
    const rawBody = "{}";
    expect(
      verifyTextlineSignature({ rawBody, signature: sign(rawBody, "wrong"), secret })
    ).toBe(false);
  });

  it("rejects when the body is tampered with after signing", () => {
    const signature = sign('{"amount":10}');
    expect(
      verifyTextlineSignature({ rawBody: '{"amount":1000}', signature, secret })
    ).toBe(false);
  });

  it("rejects a missing or empty signature", () => {
    expect(verifyTextlineSignature({ rawBody: "{}", signature: undefined, secret })).toBe(false);
    expect(verifyTextlineSignature({ rawBody: "{}", signature: "", secret })).toBe(false);
  });

  it("rejects when the secret is empty", () => {
    expect(verifyTextlineSignature({ rawBody: "{}", signature: "abc", secret: "" })).toBe(false);
  });

  it("is not thrown off by signatures of a different length", () => {
    expect(verifyTextlineSignature({ rawBody: "{}", signature: "deadbeef", secret })).toBe(false);
  });
});
