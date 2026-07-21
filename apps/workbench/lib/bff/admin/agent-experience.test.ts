import { describe, expect, it } from "vitest";
import { HermesApiClient } from "../../gateway/hermes-api-client";
import {
  handleConfirmExperienceViaApi,
  handleListAgentExperienceViaApi,
  handleRejectExperienceViaApi,
  mapAgentExperienceEntry,
} from "./agent-experience";

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

type SentDispatch = {
  tool: string;
  action: string;
  params: Record<string, unknown>;
  actor_account_id?: string;
};

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

function confirmedEntry(overrides: Record<string, unknown> = {}) {
  return {
    id: "aexp_1",
    kind: "note",
    status: "confirmed",
    content: "Route 12 customers prefer morning drop-offs.",
    source: "copilot_agent",
    proposer_context: null,
    decider_account_id: "seed-supervisor",
    decided_at: "2026-07-21T10:00:00Z",
    created_at: "2026-07-01T10:00:00Z",
    ...overrides,
  };
}

describe("handleConfirmExperienceViaApi", () => {
  it("dispatches confirm_experience with {id} as a governed WRITE (dispatchWrite, actor attributed)", async () => {
    let captured: SentDispatch | null = null;
    const client = apiClient(async (_url, init) => {
      captured = JSON.parse(init.body as string) as SentDispatch;
      return dispatchResponse(confirmedEntry());
    });

    const res = await handleConfirmExperienceViaApi(client, "aexp_1");
    expect(res.status).toBe(200);
    const body = (await res.json()) as { entry: unknown };
    expect(body.entry).toMatchObject({
      id: "aexp_1",
      status: "confirmed",
      deciderAccountId: "seed-supervisor",
    });

    const sent = captured as SentDispatch | null;
    expect(sent?.tool).toBe("toee_agent_experience");
    expect(sent?.action).toBe("confirm_experience");
    expect(sent?.params).toEqual({ id: "aexp_1" });
    // dispatchWrite attaches the actor from the client's actorAccountId.
    expect(sent?.actor_account_id).toBe("seed-supervisor");
  });

  it("maps a policy_blocked denial (e.g. no attributed actor) to 403 (ADR-0104)", async () => {
    const res = await handleConfirmExperienceViaApi(
      apiClient(
        async () =>
          new Response(
            JSON.stringify({ ok: false, error: { class: "policy_blocked", message: "no" } }),
            { status: 200 },
          ),
      ),
      "aexp_1",
    );
    expect(res.status).toBe(403);
  });

  it("maps a not_found denial (unknown id) to 404", async () => {
    const res = await handleConfirmExperienceViaApi(
      apiClient(
        async () =>
          new Response(
            JSON.stringify({ ok: false, error: { class: "not_found", message: "no" } }),
            { status: 200 },
          ),
      ),
      "aexp_missing",
    );
    expect(res.status).toBe(404);
  });
});

describe("handleRejectExperienceViaApi", () => {
  it("dispatches reject_experience with {id}", async () => {
    let captured: SentDispatch | null = null;
    const client = apiClient(async (_url, init) => {
      captured = JSON.parse(init.body as string) as SentDispatch;
      return dispatchResponse(confirmedEntry({ status: "rejected" }));
    });

    const res = await handleRejectExperienceViaApi(client, "aexp_1");
    expect(res.status).toBe(200);
    const body = (await res.json()) as { entry: { status: string } };
    expect(body.entry.status).toBe("rejected");

    const sent = captured as SentDispatch | null;
    expect(sent?.tool).toBe("toee_agent_experience");
    expect(sent?.action).toBe("reject_experience");
    expect(sent?.params).toEqual({ id: "aexp_1" });
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
