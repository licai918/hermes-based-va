import { createHmac, timingSafeEqual } from "node:crypto";

// Textline webhook authenticity check (ADR-0021). v1 uses an HMAC-SHA256 of the
// exact raw request body keyed by the shared webhook secret, hex-encoded, and
// compared in constant time against the provider signature header. The header
// name and any version prefix are extracted by the route layer (issue #17); this
// function operates purely on the already-extracted signature string so the
// crypto core stays provider-agnostic and unit-testable.
export interface TextlineSignatureInput {
  /** Exact bytes of the request body as received, before JSON parsing. */
  rawBody: string;
  /** Signature value pulled from the provider header, if any. */
  signature: string | undefined;
  /** Shared Textline webhook secret. */
  secret: string;
}

export function verifyTextlineSignature(input: TextlineSignatureInput): boolean {
  const { rawBody, signature, secret } = input;
  if (!signature || !secret) {
    return false;
  }
  const expected = createHmac("sha256", secret).update(rawBody, "utf8").digest("hex");
  const expectedBuf = Buffer.from(expected, "utf8");
  const providedBuf = Buffer.from(signature, "utf8");
  // timingSafeEqual throws on unequal lengths; bail first so a length mismatch
  // cannot leak timing or crash the verifier.
  if (expectedBuf.length !== providedBuf.length) {
    return false;
  }
  return timingSafeEqual(expectedBuf, providedBuf);
}
