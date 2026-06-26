import { describe, expect, it } from "vitest";
import { GET } from "./route";

// Cloud Run liveness probe (ADR-0098, issue #33): a dependency-free 200 the
// platform health check can hit before the app has any session or data wiring.
describe("GET /healthz", () => {
  it("returns 200 with { status: 'ok' }", async () => {
    const res = await GET();
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ status: "ok" });
  });
});
