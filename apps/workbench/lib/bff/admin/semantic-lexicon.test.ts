import { describe, expect, it } from "vitest";
import { HermesAgentClient } from "../../gateway/hermes-agent-client";
import { HermesApiClient } from "../../gateway/hermes-api-client";
import {
  handleAddLexiconViaApi,
  handleDecideLexiconViaApi,
  handleDraftLexiconViaApi,
  handleEditLexiconViaApi,
  handleListLexiconViaApi,
  mapLexiconEntry,
} from "./semantic-lexicon";

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

function governedError(cls: string): Response {
  return new Response(JSON.stringify({ ok: false, error: { class: cls, message: "no" } }), {
    status: 200,
  });
}

function rawEntry(overrides: Record<string, unknown> = {}) {
  return {
    id: "lex_1",
    domain: "company",
    entry_kind: "alias",
    surface_form: "TOEE",
    canonical_form: "TOEE TIRE",
    status: "proposed",
    provenance: "conversation_confirmed",
    evidence: "Customer wrote TOEE.",
    proposer_context: { case_id: "case_1" },
    pii_redacted: false,
    decider_account_id: null,
    provenance_unattributed: false,
    decided_at: null,
    hit_count: 7,
    created_at: "2026-07-01T10:00:00Z",
    updated_at: "2026-07-01T10:00:00Z",
    ...overrides,
  };
}

describe("handleListLexiconViaApi", () => {
  it("dispatches the ONE read action and maps snake_case to camelCase", async () => {
    let captured: SentDispatch | null = null;
    const client = apiClient(async (_url, init) => {
      captured = JSON.parse(init.body as string) as SentDispatch;
      return dispatchResponse({
        entries: [rawEntry()],
        lexicon_version: "2026-07-01T10:00:00Z",
      });
    });

    const res = await handleListLexiconViaApi(client);

    expect(res.status).toBe(200);
    const body = (await res.json()) as {
      entries: unknown[];
      lexiconVersion: string | null;
    };
    expect(body.entries[0]).toMatchObject({
      id: "lex_1",
      domain: "company",
      entryKind: "alias",
      surfaceForm: "TOEE",
      canonicalForm: "TOEE TIRE",
      status: "proposed",
      provenance: "conversation_confirmed",
      piiRedacted: false,
      provenanceUnattributed: false,
      hitCount: 7,
    });
    expect(body.lexiconVersion).toBe("2026-07-01T10:00:00Z");

    const sent = captured as SentDispatch | null;
    expect(sent?.tool).toBe("toee_semantic_lexicon");
    // S01's read action, EXTENDED with filters -- never a second read action.
    expect(sent?.action).toBe("list_lexicon_entries");
    expect(sent?.params).toEqual({});
  });

  it("forwards only the filters that were supplied", async () => {
    let captured: SentDispatch | null = null;
    const client = apiClient(async (_url, init) => {
      captured = JSON.parse(init.body as string) as SentDispatch;
      return dispatchResponse({ entries: [] });
    });

    await handleListLexiconViaApi(client, { status: "proposed" });

    expect((captured as SentDispatch | null)?.params).toEqual({ status: "proposed" });
  });

  it("surfaces the D20 unattributed flag the server derived", async () => {
    const client = apiClient(async () =>
      dispatchResponse({
        entries: [
          rawEntry({
            provenance: "admin_manual",
            decider_account_id: null,
            provenance_unattributed: true,
          }),
        ],
      }),
    );
    const body = (await (await handleListLexiconViaApi(client)).json()) as {
      entries: { provenanceUnattributed: boolean; deciderAccountId: string | null }[];
    };
    expect(body.entries[0]?.provenanceUnattributed).toBe(true);
    expect(body.entries[0]?.deciderAccountId).toBeNull();
  });

  it("maps a governed denial to its per-class status (ADR-0104)", async () => {
    const res = await handleListLexiconViaApi(
      apiClient(async () => governedError("policy_blocked")),
    );
    expect(res.status).toBe(403);
  });
});

describe("handleDecideLexiconViaApi", () => {
  it.each([
    ["confirm", "confirm_lexicon_entry", "confirmed"],
    ["reject", "reject_lexicon_entry", "rejected"],
    ["retire", "retire_lexicon_entry", "retired"],
  ] as const)(
    "dispatches %s as a governed WRITE with the attributed actor",
    async (decision, action, status) => {
      let captured: SentDispatch | null = null;
      const client = apiClient(async (_url, init) => {
        captured = JSON.parse(init.body as string) as SentDispatch;
        return dispatchResponse(
          rawEntry({ status, decider_account_id: "seed-supervisor" }),
        );
      });

      const res = await handleDecideLexiconViaApi(client, decision, "lex_1");

      expect(res.status).toBe(200);
      const body = (await res.json()) as { entry: { status: string } };
      expect(body.entry.status).toBe(status);
      const sent = captured as SentDispatch | null;
      expect(sent?.action).toBe(action);
      expect(sent?.params).toEqual({ id: "lex_1" });
      expect(sent?.actor_account_id).toBe("seed-supervisor");
    },
  );

  it("refuses before the network call when no actor is configured (D20 at the BFF)", async () => {
    let called = false;
    const client = new HermesApiClient({
      baseUrl: "http://copilot.internal",
      token: "tok",
      // No actorAccountId at all -- the shape a route that forgot to wire the
      // session would produce.
      fetchImpl: async () => {
        called = true;
        return dispatchResponse(rawEntry());
      },
    });

    const res = await handleDecideLexiconViaApi(client, "confirm", "lex_1");

    expect(res.status).toBe(403);
    expect(called).toBe(false);
  });

  it("maps not_found to 404", async () => {
    const res = await handleDecideLexiconViaApi(
      apiClient(async () => governedError("not_found")),
      "confirm",
      "lex_missing",
    );
    expect(res.status).toBe(404);
  });
});

describe("handleEditLexiconViaApi", () => {
  it("forwards only the supplied fields, so an omitted one means unchanged (D7)", async () => {
    let captured: SentDispatch | null = null;
    const client = apiClient(async (_url, init) => {
      captured = JSON.parse(init.body as string) as SentDispatch;
      return dispatchResponse(rawEntry({ canonical_form: "TOEE TIRE LTD" }));
    });

    const res = await handleEditLexiconViaApi(client, "lex_1", {
      canonicalForm: "TOEE TIRE LTD",
    });

    expect(res.status).toBe(200);
    const body = (await res.json()) as { entry: { id: string; canonicalForm: string } };
    // Same id back: an edit is an in-place UPDATE, never a delete-and-recreate.
    expect(body.entry.id).toBe("lex_1");
    expect(body.entry.canonicalForm).toBe("TOEE TIRE LTD");
    expect((captured as SentDispatch | null)?.params).toEqual({
      id: "lex_1",
      canonical_form: "TOEE TIRE LTD",
    });
  });

  it("maps a UNIQUE(domain, surface_form) collision to 409", async () => {
    const res = await handleEditLexiconViaApi(
      apiClient(async () => governedError("conflict")),
      "lex_1",
      { surfaceForm: "2055516" },
    );
    expect(res.status).toBe(409);
  });
});

describe("handleAddLexiconViaApi", () => {
  it("dispatches add_lexicon_entry and returns the confirmed entry as 201", async () => {
    let captured: SentDispatch | null = null;
    const client = apiClient(async (_url, init) => {
      captured = JSON.parse(init.body as string) as SentDispatch;
      return dispatchResponse(
        rawEntry({
          status: "confirmed",
          provenance: "admin_manual",
          decider_account_id: "seed-supervisor",
          decided_at: "2026-07-21T10:00:00Z",
        }),
      );
    });

    const res = await handleAddLexiconViaApi(client, {
      domain: "company",
      entryKind: "alias",
      surfaceForm: "TOEE",
      canonicalForm: "TOEE TIRE",
    });

    expect(res.status).toBe(201);
    const body = (await res.json()) as {
      entry: { status: string; provenance: string; deciderAccountId: string | null };
    };
    // US1: live immediately, attributed -- the admin IS the gate.
    expect(body.entry).toMatchObject({
      status: "confirmed",
      provenance: "admin_manual",
      deciderAccountId: "seed-supervisor",
      provenanceUnattributed: false,
    });
    const sent = captured as SentDispatch | null;
    expect(sent?.action).toBe("add_lexicon_entry");
    expect(sent?.params).toEqual({
      domain: "company",
      entry_kind: "alias",
      surface_form: "TOEE",
      canonical_form: "TOEE TIRE",
    });
  });

  it("maps a policy_blocked denial (injection content, no actor) to 403", async () => {
    const res = await handleAddLexiconViaApi(
      apiClient(async () => governedError("policy_blocked")),
      { domain: "company", entryKind: "alias", surfaceForm: "x", canonicalForm: "y" },
    );
    expect(res.status).toBe(403);
  });
});

describe("mapLexiconEntry", () => {
  it("rejects an unknown entry_kind", () => {
    expect(() => mapLexiconEntry(rawEntry({ entry_kind: "glossary" }))).toThrow();
  });

  it("rejects an unknown status", () => {
    expect(() => mapLexiconEntry(rawEntry({ status: "pending" }))).toThrow();
  });

  it("rejects an unknown provenance", () => {
    expect(() => mapLexiconEntry(rawEntry({ provenance: "guessed" }))).toThrow();
  });

  it("rejects a missing id", () => {
    const { id: _id, ...withoutId } = rawEntry();
    expect(() => mapLexiconEntry(withoutId)).toThrow();
  });

  // --- 0.0.5 S26 (FR-31): the health block --------------------------------

  const health = {
    score: 0.63,
    scope: "External customer turns only.",
    basis: "Turn-level attribution.",
    usage: { hits: 4, injections: 6, saturation: 10 },
    honored: { rate: 0.9, passed: 9, determinate: 10, undetermined: 1 },
    misapplied: { rate: 0.125, passed: 7, determinate: 8, undetermined: 0 },
    stale: { rate: null, passed: 0, determinate: 0, undetermined: 0 },
    weights: { usage: 0.5, honored: 0.5, misapplied: 0.3, stale: 0.2 },
  };

  it("maps the score, every component and both caveats", () => {
    const mapped = mapLexiconEntry(rawEntry({ entry_health: health }));
    expect(mapped.health?.score).toBe(0.63);
    expect(mapped.health?.honored).toEqual({
      rate: 0.9,
      passed: 9,
      determinate: 10,
      undetermined: 1,
    });
    // A leg with no denominator stays null across the wire. Coercing it to 0
    // here would turn "nobody scored this" into "this never went stale".
    expect(mapped.health?.stale.rate).toBeNull();
    expect(mapped.health?.usage.injections).toBe(6);
    expect(mapped.health?.scope).toBe(health.scope);
  });

  it("is null when the server sent no health at all", () => {
    expect(mapLexiconEntry(rawEntry()).health).toBeNull();
  });

  it("refuses a score that arrived without its scope or its basis", () => {
    // The caveats are load-bearing, not decoration: a bare number would render
    // as "this entry's effectiveness everywhere", which it is not. Dropping the
    // whole block is the honest outcome -- the console then says "not computed"
    // instead of showing a number nobody can read correctly.
    const { scope: _s, ...noScope } = health;
    expect(mapLexiconEntry(rawEntry({ entry_health: noScope })).health).toBeNull();
    const { basis: _b, ...noBasis } = health;
    expect(mapLexiconEntry(rawEntry({ entry_health: noBasis })).health).toBeNull();
  });
});

// --- 0.0.5 S17 (FR-24): the NL prefill --------------------------------------

function agentClient(
  fetchImpl: (url: string, init: RequestInit) => Promise<Response>,
): HermesAgentClient {
  return new HermesAgentClient({
    baseUrl: "http://copilot.internal",
    token: "tok",
    actorAccountId: "seed-supervisor",
    fetchImpl,
  });
}

describe("handleDraftLexiconViaApi", () => {
  it("posts the admin's sentence to the draft route and returns the fields", async () => {
    let url = "";
    let body: Record<string, unknown> = {};
    const agent = agentClient(async (u, init) => {
      url = u;
      body = JSON.parse(init.body as string) as Record<string, unknown>;
      return new Response(
        JSON.stringify({
          ok: true,
          data: {
            drafted: true,
            fields: {
              domain: "company",
              entryKind: "alias",
              surfaceForm: "拓意",
              canonicalForm: "TOEE TIRE",
            },
            model: "test/model",
          },
        }),
        { status: 200 },
      );
    });

    const res = await handleDraftLexiconViaApi(agent, "TOEE 也叫拓意");
    expect(res.status).toBe(200);
    expect(url).toBe("http://copilot.internal/v1/lexicon:draft");
    expect(body.text).toBe("TOEE 也叫拓意");
    const payload = (await res.json()) as { draft: { fields: Record<string, string> } };
    // Distinctive values that could only have come from the draft: the form's
    // own defaults are empty and "alias".
    expect(payload.draft.fields.canonicalForm).toBe("TOEE TIRE");
    expect(payload.draft.fields.surfaceForm).toBe("拓意");
  });

  it("passes a refusal through on a 200 rather than turning it into an error", async () => {
    // The form has to stay usable. A 502 here would blank the console because
    // the copilot had nothing to say about a sentence.
    const agent = agentClient(async () =>
      new Response(
        JSON.stringify({ ok: true, data: { drafted: false, reason: "could not read it" } }),
        { status: 200 },
      ),
    );
    const res = await handleDraftLexiconViaApi(agent, "asdfgh");
    expect(res.status).toBe(200);
    const payload = (await res.json()) as { draft: { drafted: boolean; reason: string } };
    expect(payload.draft.drafted).toBe(false);
    expect(payload.draft.reason).toBe("could not read it");
  });

  it("400s an empty sentence without spending a call", async () => {
    let called = false;
    const agent = agentClient(async () => {
      called = true;
      return new Response(JSON.stringify({ ok: true, data: {} }), { status: 200 });
    });
    expect((await handleDraftLexiconViaApi(agent, "   ")).status).toBe(400);
    expect(called).toBe(false);
  });

  it("maps a transport failure onto the governed problem shape, naming the draft", async () => {
    // The message reaches the admin's screen beside the draft box. Before this
    // was parameterised it read "agent turn failed", describing a turn nobody
    // asked for — seen for real when the dispatch container was serving an
    // image without the draft route.
    const agent = agentClient(async () => new Response("nope", { status: 503 }));
    const res = await handleDraftLexiconViaApi(agent, "TOEE 也叫拓意");
    expect(res.status).toBe(502);
    expect(await res.json()).toMatchObject({
      error: expect.stringContaining("lexicon draft"),
    });
  });
});

describe("handleAddLexiconViaApi prefill provenance", () => {
  async function capture(body: Parameters<typeof handleAddLexiconViaApi>[1]) {
    let captured: SentDispatch | null = null;
    const client = apiClient(async (_url, init) => {
      captured = JSON.parse(init.body as string) as SentDispatch;
      return dispatchResponse(rawEntry());
    });
    await handleAddLexiconViaApi(client, body);
    return captured as unknown as SentDispatch;
  }

  const valid = {
    domain: "company",
    entryKind: "alias",
    surfaceForm: "拓意",
    canonicalForm: "TOEE TIRE",
  };

  it("forwards the prefill record on the existing proposer_context param", async () => {
    const sent = await capture({
      ...valid,
      proposerContext: {
        nl_prefill: { source: "copilot_draft", accepted_unchanged: ["surface_form"] },
      },
    });
    expect(sent.action).toBe("add_lexicon_entry");
    expect(sent.params.proposer_context).toEqual({
      nl_prefill: { source: "copilot_draft", accepted_unchanged: ["surface_form"] },
    });
  });

  it("omits it entirely for a hand-typed entry", async () => {
    // The load-bearing half: absence is how a reader tells a hand-typed row
    // from a prefilled one. An empty object here would make every row look
    // prefilled.
    const sent = await capture(valid);
    expect(sent.params).not.toHaveProperty("proposer_context");
  });
});
