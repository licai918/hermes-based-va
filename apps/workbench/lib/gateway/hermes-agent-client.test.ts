import { describe, expect, it } from "vitest";
import { HermesAgentClient } from "./hermes-agent-client";
import { HermesApiError } from "./hermes-api-client";

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

const smsDraft = {
  channel: "sms",
  draft: "Hi! Your order ships today.",
  provenance: { model: "scripted", profile: "internal_copilot" },
};

describe("HermesAgentClient.generateDraft", () => {
  it("POSTs the agent-turn envelope with a bearer token and returns data", async () => {
    let captured: { url: string; init: RequestInit } | undefined;
    const client = new HermesAgentClient({
      baseUrl: BASE,
      token: TOKEN,
      fetchImpl: async (url, init) => {
        captured = { url, init };
        return okResponse(smsDraft);
      },
    });

    const data = await client.generateDraft({ channel: "sms", caseId: "case_1" });

    expect(data).toEqual(smsDraft);
    if (!captured) throw new Error("expected fetch to be called");
    // ADR-0147: a distinct AIP-136 custom method, not tools:dispatch.
    expect(captured.url).toBe(`${BASE}/v1/agent:turn`);
    expect(captured.init.method).toBe("POST");
    const headers = new Headers(captured.init.headers);
    expect(headers.get("authorization")).toBe(`Bearer ${TOKEN}`);
    expect(JSON.parse(captured.init.body as string)).toEqual({
      channel: "sms",
      case_id: "case_1",
    });
  });

  it("includes the acting account id (actor_account_id) when configured", async () => {
    // ADR-0141 actor attribution convention, reused on the agent-turn route.
    let captured: RequestInit | undefined;
    const client = new HermesAgentClient({
      baseUrl: BASE,
      token: TOKEN,
      actorAccountId: "acct_rep_7",
      fetchImpl: async (_url, init) => {
        captured = init;
        return okResponse(smsDraft);
      },
    });

    await client.generateDraft({ channel: "sms", caseId: "case_1", prompt: "be kind" });

    if (!captured) throw new Error("expected fetch to be called");
    expect(JSON.parse(captured.body as string)).toEqual({
      channel: "sms",
      case_id: "case_1",
      prompt: "be kind",
      actor_account_id: "acct_rep_7",
    });
  });

  it("omits actor_account_id and prompt when not provided", async () => {
    let captured: RequestInit | undefined;
    const client = new HermesAgentClient({
      baseUrl: BASE,
      token: TOKEN,
      fetchImpl: async (_url, init) => {
        captured = init;
        return okResponse(smsDraft);
      },
    });

    await client.generateDraft({ channel: "sms", caseId: "case_1" });

    if (!captured) throw new Error("expected fetch to be called");
    const body = JSON.parse(captured.body as string);
    expect(body).not.toHaveProperty("actor_account_id");
    expect(body).not.toHaveProperty("prompt");
  });

  it("strips a trailing slash from the base URL", async () => {
    const calls: string[] = [];
    const client = new HermesAgentClient({
      baseUrl: `${BASE}/`,
      token: TOKEN,
      fetchImpl: async (url) => {
        calls.push(url);
        return okResponse(smsDraft);
      },
    });

    await client.generateDraft({ channel: "sms", caseId: "case_1" });

    expect(calls[0]).toBe(`${BASE}/v1/agent:turn`);
  });

  it("throws HermesApiError carrying the governed error class on ok:false", async () => {
    const client = new HermesAgentClient({
      baseUrl: BASE,
      token: TOKEN,
      fetchImpl: async () => governedFailure("policy_blocked"),
    });

    await expect(
      client.generateDraft({ channel: "sms", caseId: "case_1" }),
    ).rejects.toMatchObject({ errorClass: "policy_blocked" });
  });

  it("throws HermesApiError on a non-2xx transport failure", async () => {
    const client = new HermesAgentClient({
      baseUrl: BASE,
      token: TOKEN,
      fetchImpl: async () => new Response("nope", { status: 502 }),
    });

    await expect(
      client.generateDraft({ channel: "sms", caseId: "case_1" }),
    ).rejects.toBeInstanceOf(HermesApiError);
  });
});
