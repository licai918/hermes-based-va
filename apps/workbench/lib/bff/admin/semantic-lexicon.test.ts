import { describe, expect, it } from "vitest";
import { HermesApiClient } from "../../gateway/hermes-api-client";
import {
  handleAddLexiconViaApi,
  handleDecideLexiconViaApi,
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
});
