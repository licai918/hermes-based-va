import { describe, expect, it } from "vitest";
import { HermesApiClient, HermesApiError } from "./hermes-api-client";
import type { WorkbenchCase } from "./types";

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

describe("HermesApiClient.listCases", () => {
  it("dispatches list_cases with the filter and returns the cases array", async () => {
    const apiCase = { caseId: "case_api" } as WorkbenchCase;
    let body: { tool: string; action: string; params: unknown } | null = null;
    const client = new HermesApiClient({
      baseUrl: BASE,
      token: TOKEN,
      fetchImpl: async (_url, init) => {
        body = JSON.parse(init.body as string);
        return okResponse({ cases: [apiCase] });
      },
    });

    const cases = await client.listCases({
      statuses: ["open"],
      assignee: { mode: "all" },
    });

    expect(cases).toEqual([apiCase]);
    expect(body).toEqual({
      tool: "toee_workbench_read",
      action: "list_cases",
      params: { statuses: ["open"], assignee: { mode: "all" } },
    });
  });

  it("returns an empty array when the dispatch data has no cases", async () => {
    const client = new HermesApiClient({
      baseUrl: BASE,
      token: TOKEN,
      fetchImpl: async () => okResponse({}),
    });

    expect(await client.listCases({})).toEqual([]);
  });
});
