import { describe, expect, it } from "vitest";
import { HermesApiError } from "./hermes-api-client";
import { errorClassToStatus, hermesErrorToProblem } from "./hermes-error";

describe("errorClassToStatus", () => {
  it("maps a Tool Gate denial to 403 (ADR-0090 governed denial)", () => {
    expect(errorClassToStatus("policy_blocked")).toBe(403);
  });

  it("maps an ADR-0018 lockout to 423, distinct from 401/403", () => {
    expect(errorClassToStatus("locked")).toBe(423);
    expect(errorClassToStatus("unauthenticated")).toBe(401);
  });

  it("maps a vendor timeout to 504 (ADR-0104 retryable upstream)", () => {
    expect(errorClassToStatus("vendor_timeout")).toBe(504);
  });

  it("maps missing integration configuration to 503", () => {
    expect(errorClassToStatus("configuration_missing")).toBe(503);
  });

  it("maps an unknown tool/action contract bug to 500", () => {
    expect(errorClassToStatus("unknown_tool")).toBe(500);
    expect(errorClassToStatus("unknown_action")).toBe(500);
  });

  it("maps upstream integration failures to 502", () => {
    expect(errorClassToStatus("auth_expired")).toBe(502);
    expect(errorClassToStatus("composio_api_error")).toBe(502);
    expect(errorClassToStatus("unexpected_error")).toBe(502);
    expect(errorClassToStatus("transport_error")).toBe(502);
  });

  it("defaults an unrecognised class to 502", () => {
    expect(errorClassToStatus("something_new")).toBe(502);
  });
});

describe("hermesErrorToProblem", () => {
  it("maps a HermesApiError onto its class status and echoes the class", async () => {
    const res = hermesErrorToProblem(
      new HermesApiError("policy_blocked", "denied by Tool Gate"),
    );
    expect(res.status).toBe(403);
    const body = (await res.json()) as { error: string; errorClass: string };
    expect(body.errorClass).toBe("policy_blocked");
    expect(body.error).toBe("denied by Tool Gate");
  });

  it("maps a transport failure to 502", () => {
    const res = hermesErrorToProblem(
      new HermesApiError("transport_error", "tool dispatch failed: HTTP 500", 500),
    );
    expect(res.status).toBe(502);
  });

  it("treats a non-Hermes throw as an unexpected 502 governed failure", async () => {
    const res = hermesErrorToProblem(new Error("boom"));
    expect(res.status).toBe(502);
    const body = (await res.json()) as { errorClass: string };
    expect(body.errorClass).toBe("unexpected_error");
  });
});
