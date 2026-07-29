import { describe, expect, it } from "vitest";
import { HermesApiClient } from "../../gateway/hermes-api-client";
import {
  INBOX_DECISION_DISPATCH,
  handleAnnotateInboxItemViaApi,
  handleDecideInboxItemViaApi,
  handleListInboxViaApi,
  handleReclassifyInboxItemViaApi,
} from "./review-inbox";

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
  return new Response(
    JSON.stringify({ ok: false, error: { class: cls, message: "no" } }),
    { status: 200 },
  );
}

// A fake dispatch endpoint that answers per (tool, action) and records every
// call, so a test can assert BOTH what came back and what was asked for.
function fakeHermes(answers: Record<string, unknown>) {
  const sent: SentDispatch[] = [];
  const client = apiClient(async (_url, init) => {
    const body = JSON.parse(init.body as string) as SentDispatch;
    sent.push(body);
    const key = `${body.tool}.${body.action}`;
    if (!(key in answers)) return governedError("configuration_missing");
    return dispatchResponse(answers[key]);
  });
  return { client, sent };
}

const L6_PENDING = {
  id: "aexp_1",
  kind: "note",
  status: "proposed",
  content: "reps confirm 2055516 means the tire size",
  source: "copilot_agent",
  proposer_context: { case_id: "case_1" },
  decider_account_id: null,
  decided_at: null,
  created_at: "2026-07-01T10:00:00Z",
};

const L6_DECIDED = {
  ...L6_PENDING,
  id: "aexp_2",
  status: "confirmed",
  content: "already decided, must not reach the inbox",
  created_at: "2026-07-05T10:00:00Z",
};

const L7_PENDING = {
  id: "lex_1",
  domain: "tire",
  entry_kind: "alias",
  surface_form: "2055516",
  canonical_form: "205/55R16",
  status: "proposed",
  provenance: "conversation_confirmed",
  evidence: "Customer wrote 2055516.",
  proposer_context: null,
  pii_redacted: false,
  decider_account_id: null,
  provenance_unattributed: false,
  decided_at: null,
  hit_count: 0,
  created_at: "2026-07-03T10:00:00Z",
  updated_at: "2026-07-03T10:00:00Z",
};

const GRADUATION_ITEM = {
  id: "rvw_1",
  kind: "graduation",
  subject_ref: "aexp_9",
  evidence: { hits: 12 },
  annotations: {},
  status: "open",
  decider_account_id: null,
  decided_at: null,
  created_at: "2026-07-02T10:00:00Z",
  updated_at: "2026-07-02T10:00:00Z",
};

function inbox(
  overrides: {
    l6?: unknown[];
    l7?: unknown[];
    items?: unknown[];
    openCount?: number;
  } = {},
) {
  return {
    "toee_agent_experience.list_agent_experience": {
      entries: overrides.l6 ?? [L6_PENDING, L6_DECIDED],
    },
    "toee_semantic_lexicon.list_lexicon_entries": {
      entries: overrides.l7 ?? [L7_PENDING],
      lexicon_version: "2026-07-03T10:00:00Z",
    },
    "toee_review_inbox.list_review_items": {
      items: overrides.items ?? [GRADUATION_ITEM],
      open_count: overrides.openCount ?? 1,
    },
  };
}

describe("handleListInboxViaApi (FR-22: ONE queue)", () => {
  it("merges the two proposal tables and the review_item store into typed, badged items", async () => {
    const { client, sent } = fakeHermes(inbox());

    const res = await handleListInboxViaApi(client);
    expect(res.status).toBe(200);
    const body = (await res.json()) as {
      items: {
        kind: string;
        layer: string | null;
        id: string;
        createdAt: number;
        reclassifiable: boolean;
      }[];
      count: number;
    };

    // Newest first, across all three sources -- not three concatenated lists.
    expect(body.items.map((i) => [i.kind, i.id])).toEqual([
      ["l7_proposal", "lex_1"],
      ["graduation", "rvw_1"],
      ["l6_proposal", "aexp_1"],
    ]);
    // The layer badge is only claimed where the kind determines it. The four
    // review_item kinds span layers their emitting slices have not landed yet,
    // and a guessed badge is worse than an honest absent one.
    expect(body.items.map((i) => i.layer)).toEqual(["L7", null, "L6"]);
    expect(body.count).toBe(3);

    // Only a mis-filed PROPOSAL can be re-classified, and only the L6 direction
    // is routed (L6's PII reject leg makes the reverse policy_blocked for the
    // digit-shaped tokens L7 exists to hold). Found missing by the red-proof:
    // without this line, `reclassifiable` could be hardcoded false and no test
    // in either file would notice -- the component tests supply the flag as a
    // prop, so they pin the RENDER, not the derivation.
    expect(body.items.map((i) => i.reclassifiable)).toEqual([false, false, true]);

    // The two proposal reads are FILTERED to what is still pending, so the
    // inbox is a queue rather than a history.
    const lexicon = sent.find((s) => s.tool === "toee_semantic_lexicon");
    expect(lexicon?.params).toEqual({ status: "proposed" });
    const items = sent.find((s) => s.tool === "toee_review_inbox");
    expect(items?.params).toEqual({ status: "open" });
  });

  it("drops an already-decided L6 proposal, which its read cannot filter server-side", async () => {
    // list_agent_experience has no status filter (0.0.3 S22 shipped it
    // unfiltered), so the pending-only rule has to hold HERE. The fixture
    // carries a decided row precisely so "filters" and "returns everything" are
    // distinguishable.
    const { client } = fakeHermes(inbox());
    const body = (await (await handleListInboxViaApi(client)).json()) as {
      items: { id: string }[];
    };
    expect(body.items.map((i) => i.id)).not.toContain("aexp_2");
  });

  it("carries S13/S16 annotations through where a row has them", async () => {
    const { client } = fakeHermes(
      inbox({
        items: [
          {
            ...GRADUATION_ITEM,
            annotations: { heuristic: { note: "looks like a lexicon entry" } },
          },
        ],
      }),
    );
    const body = (await (await handleListInboxViaApi(client)).json()) as {
      items: { annotations: Record<string, unknown> | null }[];
    };
    const graduation = body.items.find((i) => i.annotations?.heuristic);
    expect(graduation?.annotations).toEqual({
      heuristic: { note: "looks like a lexicon entry" },
    });
  });

  it("reports the count as the whole queue, not just this store's share", async () => {
    const { client } = fakeHermes(inbox({ openCount: 1 }));
    const body = (await (await handleListInboxViaApi(client)).json()) as {
      count: number;
    };
    // 1 L6 pending + 1 L7 pending + 1 open review_item.
    expect(body.count).toBe(3);
  });

  it("surfaces a governed failure as a problem response", async () => {
    const client = apiClient(async () => governedError("policy_blocked"));
    const res = await handleListInboxViaApi(client);
    expect(res.status).toBe(403);
  });
});

describe("handleDecideInboxItemViaApi (each decision routes to its OWN layer)", () => {
  const cases: [string, string, string, string, Record<string, unknown>][] = [
    [
      "l6_proposal",
      "accept",
      "toee_agent_experience",
      "confirm_experience",
      { id: "aexp_1" },
    ],
    [
      "l6_proposal",
      "reject",
      "toee_agent_experience",
      "reject_experience",
      { id: "aexp_1" },
    ],
    [
      "l7_proposal",
      "accept",
      "toee_semantic_lexicon",
      "confirm_lexicon_entry",
      { id: "aexp_1" },
    ],
    [
      "l7_proposal",
      "reject",
      "toee_semantic_lexicon",
      "reject_lexicon_entry",
      { id: "aexp_1" },
    ],
    [
      "graduation",
      "acknowledge",
      "toee_review_inbox",
      "decide_review_item",
      { id: "aexp_1", decision: "acknowledged" },
    ],
    [
      "blast_radius",
      "dismiss",
      "toee_review_inbox",
      "decide_review_item",
      { id: "aexp_1", decision: "dismissed" },
    ],
  ];

  it.each(cases)(
    "%s + %s dispatches %s.%s",
    async (kind, decision, tool, action, params) => {
      let captured: SentDispatch | null = null;
      const client = apiClient(async (_url, init) => {
        captured = JSON.parse(init.body as string) as SentDispatch;
        return dispatchResponse({ id: "aexp_1", status: "ok" });
      });

      const res = await handleDecideInboxItemViaApi(
        client,
        kind,
        "aexp_1",
        decision,
      );

      expect(res.status).toBe(200);
      expect(captured!.tool).toBe(tool);
      expect(captured!.action).toBe(action);
      expect(captured!.params).toEqual(params);
      // A decision is a governed WRITE: the acting account must ride along or
      // Hermes fails it closed (ADR-0148).
      expect(captured!.actor_account_id).toBe("seed-supervisor");
    },
  );

  it("refuses a decision the kind does not offer, without dispatching", async () => {
    // An L6 proposal has no "dismiss", and a graduation item has no "accept" --
    // the only accept/reject primitives are the layers' own. A 400 here beats a
    // 502 from a dispatch that was never going to work.
    let dispatched = false;
    const client = apiClient(async () => {
      dispatched = true;
      return dispatchResponse({});
    });

    expect((await handleDecideInboxItemViaApi(client, "l6_proposal", "a", "dismiss")).status).toBe(400);
    expect((await handleDecideInboxItemViaApi(client, "graduation", "a", "accept")).status).toBe(400);
    expect((await handleDecideInboxItemViaApi(client, "not_a_kind", "a", "accept")).status).toBe(400);
    expect(dispatched).toBe(false);
  });

  it("offers exactly the decisions each kind's own layer can honour", () => {
    // The table is the routing contract S10/S20/S25 inherit; pinning it stops a
    // later kind being added with no decision at all, which would render as a
    // row with no buttons.
    expect(Object.keys(INBOX_DECISION_DISPATCH.l6_proposal)).toEqual([
      "accept",
      "reject",
    ]);
    expect(Object.keys(INBOX_DECISION_DISPATCH.retirement_candidate)).toEqual([
      "acknowledge",
      "dismiss",
    ]);
  });
});

describe("handleReclassifyInboxItemViaApi (FR-22 Re-classify)", () => {
  it("dispatches the ONE governed action with the target the admin typed", async () => {
    let captured: SentDispatch | null = null;
    const client = apiClient(async (_url, init) => {
      captured = JSON.parse(init.body as string) as SentDispatch;
      return dispatchResponse({
        source: { ...L6_PENDING, status: "rejected" },
        target: { ...L7_PENDING },
        reclassified: {
          from: { kind: "l6_proposal", id: "aexp_1" },
          to: { kind: "l7_proposal", id: "lex_1" },
        },
      });
    });

    const res = await handleReclassifyInboxItemViaApi(client, {
      sourceKind: "l6_proposal",
      id: "aexp_1",
      domain: "tire",
      entryKind: "alias",
      surfaceForm: "2055516",
      canonicalForm: "205/55R16",
    });

    expect(res.status).toBe(200);
    expect(captured!.tool).toBe("toee_review_inbox");
    expect(captured!.action).toBe("reclassify_proposal");
    expect(captured!.params).toEqual({
      source_kind: "l6_proposal",
      id: "aexp_1",
      domain: "tire",
      entry_kind: "alias",
      surface_form: "2055516",
      canonical_form: "205/55R16",
    });
    expect(captured!.actor_account_id).toBe("seed-supervisor");

    const body = (await res.json()) as {
      target: { id: string };
      reclassified: unknown;
    };
    expect(body.target.id).toBe("lex_1");
    expect(body.reclassified).toEqual({
      from: { kind: "l6_proposal", id: "aexp_1" },
      to: { kind: "l7_proposal", id: "lex_1" },
    });
  });

  it("400s a missing target field at the BFF instead of letting it become a 502", async () => {
    // Hermes classifies a blank required field as `unexpected_error`, which the
    // house error map turns into 502 -- so a blank Domain rendered to the admin
    // as "Bad Gateway". The layer that owns the request shape owns this 400
    // (the S02 precedent).
    let dispatched = false;
    const client = apiClient(async () => {
      dispatched = true;
      return dispatchResponse({});
    });

    const res = await handleReclassifyInboxItemViaApi(client, {
      sourceKind: "l6_proposal",
      id: "aexp_1",
      domain: "  ",
      entryKind: "alias",
      surfaceForm: "2055516",
      canonicalForm: "205/55R16",
    });

    expect(res.status).toBe(400);
    expect(dispatched).toBe(false);
  });
});

// --- 0.0.5 S16 (FR-23): the on-demand re-triage ---------------------------

describe("handleAnnotateInboxItemViaApi", () => {
  it("dispatches the governed annotate action with the acting account", async () => {
    const { client, sent } = fakeHermes({
      "toee_review_inbox.annotate_inbox_item": {
        kind: "l7_proposal",
        id: "lex_1",
        annotated: true,
        annotation: { recommendation: "reject", reasoning: "already confirmed" },
        reason: null,
      },
    });

    const res = await handleAnnotateInboxItemViaApi(client, "l7_proposal", "lex_1");

    expect(res.status).toBe(200);
    expect(sent).toHaveLength(1);
    const dispatch = sent[0]!;
    expect(dispatch.tool).toBe("toee_review_inbox");
    expect(dispatch.action).toBe("annotate_inbox_item");
    expect(dispatch.params).toEqual({ kind: "l7_proposal", id: "lex_1" });
    expect(dispatch.actor_account_id).toBe("seed-supervisor");

    const body = (await res.json()) as { annotated: boolean; annotation: unknown };
    expect(body.annotated).toBe(true);
    expect(body.annotation).toEqual({
      recommendation: "reject",
      reasoning: "already confirmed",
    });
  });

  it("refuses before the network call when no acting account is configured", async () => {
    // This is what `dispatchWrite` buys over `dispatch`, and it is the ONLY
    // thing it buys -- with an actor present the two send a byte-identical
    // body, so the assertion above cannot tell them apart and swapping the call
    // leaves it green. Found by the red-proof. Re-triage spends a billed
    // completion and stores a row on a governance surface, so it belongs on the
    // fail-closed path (ADR-0141), and this is where that is checkable.
    let dispatched = false;
    const client = new HermesApiClient({
      baseUrl: "http://copilot.internal",
      token: "tok",
      fetchImpl: async () => {
        dispatched = true;
        return dispatchResponse({});
      },
    });

    const res = await handleAnnotateInboxItemViaApi(client, "graduation", "rvw_1");

    expect(res.status).toBe(403);
    expect(dispatched).toBe(false);
  });

  it("passes a not-annotated result through as a 200 with its reason", async () => {
    // Default-OFF is the SHIPPED state of FR-23. If this became an error the
    // console would show a fault for a deployment that is configured exactly as
    // intended -- and the admin would have no way to tell it from a real one.
    const { client } = fakeHermes({
      "toee_review_inbox.annotate_inbox_item": {
        kind: "graduation",
        id: "rvw_1",
        annotated: false,
        annotation: null,
        reason: "copilot triage annotations are off for this deployment",
      },
    });

    const res = await handleAnnotateInboxItemViaApi(client, "graduation", "rvw_1");

    expect(res.status).toBe(200);
    const body = (await res.json()) as { annotated: boolean; reason: string };
    expect(body.annotated).toBe(false);
    expect(body.reason).toContain("off for this deployment");
  });

  it("400s an unknown kind at the BFF instead of letting it become a 502", async () => {
    // The S02 precedent the sibling handlers pay: Hermes classifies a bad kind
    // as `unexpected_error`, which the house error map renders to the admin as
    // "Bad Gateway". The layer that owns the request shape owns this 400.
    let dispatched = false;
    const client = apiClient(async () => {
      dispatched = true;
      return dispatchResponse({});
    });

    const res = await handleAnnotateInboxItemViaApi(client, "l8_proposal", "x_1");

    expect(res.status).toBe(400);
    expect(dispatched).toBe(false);
  });

  it("maps a governed refusal to its problem status", async () => {
    const { client } = fakeHermes({});
    const res = await handleAnnotateInboxItemViaApi(client, "graduation", "rvw_1");
    expect(res.status).toBeGreaterThanOrEqual(400);
  });
});
