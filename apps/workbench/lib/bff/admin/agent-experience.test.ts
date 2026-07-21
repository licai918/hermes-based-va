import { describe, expect, it } from "vitest";
import { HermesApiClient } from "../../gateway/hermes-api-client";
import { handleListAgentExperienceViaApi, mapAgentExperienceEntry } from "./agent-experience";

function apiClient(
  fetchImpl: (url: string, init: RequestInit) => Promise<Response>,
): HermesApiClient {
  return new HermesApiClient({
    baseUrl: "http://copilot.internal",
    token: "tok",
    actorAccountId: "seed-supervisor",
    fetchImpl,
  });
}

type SentDispatch = { tool: string; action: string; params: Record<string, unknown> };

function dispatchResponse(data: unknown): Response {
  return new Response(JSON.stringify({ ok: true, data }), { status: 200 });
}

describe("handleListAgentExperienceViaApi", () => {
  it("dispatches list_agent_experience with no params and maps snake_case to camelCase", async () => {
    let captured: SentDispatch | null = null;
    const client = apiClient(async (_url, init) => {
      captured = JSON.parse(init.body as string) as SentDispatch;
      return dispatchResponse({
        entries: [
          {
            id: "aexp_1",
            kind: "note",
            status: "proposed",
            content: "Route 12 customers prefer morning drop-offs.",
            source: "copilot_agent",
            proposer_context: { case_id: "case_1" },
            decider_account_id: null,
            decided_at: null,
            created_at: "2026-07-01T10:00:00Z",
          },
        ],
      });
    });

    const res = await handleListAgentExperienceViaApi(client);
    expect(res.status).toBe(200);
    const body = (await res.json()) as { entries: unknown[] };
    expect(body.entries).toHaveLength(1);
    expect(body.entries[0]).toMatchObject({
      id: "aexp_1",
      kind: "note",
      status: "proposed",
      content: "Route 12 customers prefer morning drop-offs.",
      source: "copilot_agent",
      proposerContext: { case_id: "case_1" },
      deciderAccountId: null,
      decidedAt: null,
    });

    const sent = captured as SentDispatch | null;
    expect(sent?.tool).toBe("toee_agent_experience");
    expect(sent?.action).toBe("list_agent_experience");
    expect(sent?.params).toEqual({});
  });

  it("returns an empty list when the store has no entries", async () => {
    const client = apiClient(async () => dispatchResponse({ entries: [] }));
    const res = await handleListAgentExperienceViaApi(client);
    const body = (await res.json()) as { entries: unknown[] };
    expect(body.entries).toEqual([]);
  });

  it("maps a governed denial to its per-class status (ADR-0104)", async () => {
    const res = await handleListAgentExperienceViaApi(
      apiClient(
        async () =>
          new Response(
            JSON.stringify({ ok: false, error: { class: "policy_blocked", message: "no" } }),
            { status: 200 },
          ),
      ),
    );
    expect(res.status).toBe(403);
  });
});

describe("mapAgentExperienceEntry", () => {
  it("rejects an unknown kind", () => {
    expect(() =>
      mapAgentExperienceEntry({
        id: "aexp_1",
        kind: "skill",
        status: "proposed",
        content: "x",
        source: "copilot_agent",
        created_at: "2026-07-01T10:00:00Z",
      }),
    ).toThrow();
  });

  it("rejects a missing id", () => {
    expect(() =>
      mapAgentExperienceEntry({
        kind: "note",
        status: "proposed",
        content: "x",
        source: "copilot_agent",
        created_at: "2026-07-01T10:00:00Z",
      }),
    ).toThrow();
  });
});
