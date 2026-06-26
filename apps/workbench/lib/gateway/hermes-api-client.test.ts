import { describe, expect, it } from "vitest";
import { HermesApiClient, HermesApiError } from "./hermes-api-client";

const BASE = "http://hermes-copilot.internal";
const TOKEN = "copilot-api-token";

function okResponse(data: unknown): Response {
  return new Response(JSON.stringify({ ok: true, data }), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

function governedFailure(errorClass: string, message = "blocked"): Response {
  return new Response(
    JSON.stringify({ ok: false, error: { class: errorClass, message } }),
    { status: 200, headers: { "content-type": "application/json" } },
  );
}

describe("HermesApiClient.dispatch", () => {
  it("POSTs the tool envelope with a bearer token and returns data", async () => {
    let captured: { url: string; init: RequestInit } | undefined;
    const client = new HermesApiClient({
      baseUrl: BASE,
      token: TOKEN,
      fetchImpl: async (url, init) => {
        captured = { url, init };
        return okResponse({ cases: [] });
      },
    });

    const data = await client.dispatch("toee_workbench_read", "list_cases", {
      statuses: ["open"],
    });

    expect(data).toEqual({ cases: [] });
    if (!captured) throw new Error("expected fetch to be called");
    expect(captured.url).toBe(`${BASE}/v1/tools:dispatch`);
    expect(captured.init.method).toBe("POST");
    const headers = new Headers(captured.init.headers);
    expect(headers.get("authorization")).toBe(`Bearer ${TOKEN}`);
    expect(JSON.parse(captured.init.body as string)).toEqual({
      tool: "toee_workbench_read",
      action: "list_cases",
      params: { statuses: ["open"] },
    });
  });

  it("includes the acting account id (actor_account_id) when configured", async () => {
    // ADR-0141 actor attribution: the BFF bakes the acting workbench account into
    // the client so every governed write/read audits to the real employee, not NULL.
    let captured: RequestInit | undefined;
    const client = new HermesApiClient({
      baseUrl: BASE,
      token: TOKEN,
      actorAccountId: "acct_rep_7",
      fetchImpl: async (_url, init) => {
        captured = init;
        return okResponse({});
      },
    });

    await client.dispatch("toee_case_manage", "claim_case", { case_id: "c1" });

    if (!captured) throw new Error("expected fetch to be called");
    expect(JSON.parse(captured.body as string)).toEqual({
      tool: "toee_case_manage",
      action: "claim_case",
      params: { case_id: "c1" },
      actor_account_id: "acct_rep_7",
    });
  });

  it("omits actor_account_id when no acting account is configured", async () => {
    let captured: RequestInit | undefined;
    const client = new HermesApiClient({
      baseUrl: BASE,
      token: TOKEN,
      fetchImpl: async (_url, init) => {
        captured = init;
        return okResponse({});
      },
    });

    await client.dispatch("toee_workbench_read", "list_cases");

    if (!captured) throw new Error("expected fetch to be called");
    expect(JSON.parse(captured.body as string)).not.toHaveProperty(
      "actor_account_id",
    );
  });

  it("strips a trailing slash from the base URL", async () => {
    const calls: string[] = [];
    const client = new HermesApiClient({
      baseUrl: `${BASE}/`,
      token: TOKEN,
      fetchImpl: async (url) => {
        calls.push(url);
        return okResponse({});
      },
    });

    await client.dispatch("toee_workbench_read", "list_cases");

    expect(calls[0]).toBe(`${BASE}/v1/tools:dispatch`);
  });

  it("throws HermesApiError carrying the governed error class on ok:false", async () => {
    const client = new HermesApiClient({
      baseUrl: BASE,
      token: TOKEN,
      fetchImpl: async () => governedFailure("policy_blocked"),
    });

    await expect(
      client.dispatch("toee_workbench_admin", "list_accounts"),
    ).rejects.toMatchObject({ errorClass: "policy_blocked" });
  });

  it("throws on a non-2xx transport failure", async () => {
    const client = new HermesApiClient({
      baseUrl: BASE,
      token: TOKEN,
      fetchImpl: async () => new Response("nope", { status: 401 }),
    });

    await expect(
      client.dispatch("toee_workbench_read", "list_cases"),
    ).rejects.toBeInstanceOf(HermesApiError);
  });
});

describe("HermesApiClient.dispatchWrite", () => {
  it("dispatches the governed write when an actor is configured", async () => {
    let captured: RequestInit | undefined;
    const client = new HermesApiClient({
      baseUrl: BASE,
      token: TOKEN,
      actorAccountId: "acct_rep_7",
      fetchImpl: async (_url, init) => {
        captured = init;
        return okResponse({ claimed: true });
      },
    });

    const data = await client.dispatchWrite("toee_case_manage", "claim_case", {
      case_id: "c1",
    });

    expect(data).toEqual({ claimed: true });
    if (!captured) throw new Error("expected fetch to be called");
    expect(JSON.parse(captured.body as string)).toMatchObject({
      actor_account_id: "acct_rep_7",
    });
  });

  it("fails closed (governed policy_blocked, no network) without an actor", async () => {
    // I1: a write with no acting account must never reach the server — the audit
    // (and, for claim/resolve, the mutation) would otherwise attribute to NULL.
    let called = false;
    const client = new HermesApiClient({
      baseUrl: BASE,
      token: TOKEN,
      fetchImpl: async () => {
        called = true;
        return okResponse({});
      },
    });

    await expect(
      client.dispatchWrite("toee_case_manage", "claim_case", { case_id: "c1" }),
    ).rejects.toMatchObject({ errorClass: "policy_blocked" });
    expect(called).toBe(false);
  });
});
