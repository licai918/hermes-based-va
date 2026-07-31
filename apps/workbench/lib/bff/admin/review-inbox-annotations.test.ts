// 0.0.5 S13 (FR-18, D8): the inbox carries write-time advisories off the two
// PROPOSAL rows, not just off `review_item`.
//
// WHY THIS IS A SEPARATE FILE, and why it exists at all. `annotationsOf` in
// review-inbox.ts runs on THREE sources -- the stored review_item and the two
// proposal tables -- and S15 shipped it before either proposal table had an
// `annotations` column, with a test covering only the review_item branch. So
// the two proposal branches could have been hardcoded `null` from the day they
// were written and the whole suite would have stayed green.
//
// S13 is the event that guard was written for: migration 0025 puts the column
// on `agent_experience` and `semantic_lexicon`, and this slice fills it. Proving
// the guard fires is therefore the first thing S13 owes -- verified by setting
// both proposal branches to `null` and watching exactly this file go red while
// the other fifteen tests in review-inbox.test.ts stayed green.
import { describe, expect, it } from "vitest";
import { HermesApiClient } from "../../gateway/hermes-api-client";
import { handleListInboxViaApi } from "./review-inbox";

function fakeHermes(answers: Record<string, unknown>) {
  const client = new HermesApiClient({
    baseUrl: "http://copilot.internal",
    token: "tok",
    actorAccountId: "seed-supervisor",
    fetchImpl: async (_url, init) => {
      const body = JSON.parse(init.body as string) as { tool: string; action: string };
      const data = answers[`${body.tool}.${body.action}`];
      return new Response(JSON.stringify({ ok: true, data }), { status: 200 });
    },
  });
  return client;
}

// One blob, the shape toee_hermes/write_advisories.py actually emits.
const HEURISTIC = {
  advisories: [
    { code: "refile_to_l7", surface_form: "2055516", canonical_form: "205/55R16" },
  ],
};

const L6_PROPOSAL = {
  id: "aexp_1",
  kind: "note",
  status: "proposed",
  content: "2055516 means 205/55R16",
  source: "copilot_agent",
  proposer_context: null,
  annotations: { heuristic: HEURISTIC },
  decider_account_id: null,
  decided_at: null,
  created_at: "2026-07-01T10:00:00Z",
};

const L7_PROPOSAL = {
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
  annotations: { heuristic: HEURISTIC },
  decider_account_id: null,
  provenance_unattributed: false,
  decided_at: null,
  hit_count: 0,
  created_at: "2026-07-03T10:00:00Z",
  updated_at: "2026-07-03T10:00:00Z",
};

// Deliberately UNannotated, and deliberately in the same fixture: without a row
// that must come back `null`, this file would pass against a mapper that
// attached the same blob to everything.
const UNANNOTATED_ITEM = {
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

describe("handleListInboxViaApi + S13 write-time advisories (FR-18)", () => {
  it("carries the heuristic block off BOTH proposal rows and nothing off an unannotated one", async () => {
    const client = fakeHermes({
      "toee_agent_experience.list_agent_experience": { entries: [L6_PROPOSAL] },
      "toee_semantic_lexicon.list_lexicon_entries": {
        entries: [L7_PROPOSAL],
        lexicon_version: "2026-07-03T10:00:00Z",
      },
      "toee_review_inbox.list_review_items": {
        items: [UNANNOTATED_ITEM],
        open_count: 1,
      },
    });

    const body = (await (await handleListInboxViaApi(client)).json()) as {
      items: { kind: string; annotations: Record<string, unknown> | null }[];
    };
    const byKind = Object.fromEntries(body.items.map((i) => [i.kind, i.annotations]));

    expect(byKind.l6_proposal).toEqual({ heuristic: HEURISTIC });
    expect(byKind.l7_proposal).toEqual({ heuristic: HEURISTIC });
    expect(byKind.graduation).toBeNull();
  });

  it("leaves a proposal row alone when it carries no advisories", async () => {
    // The column defaults to `{}` (migration 0025), which is what every row
    // written before this slice holds. `{}` must render as no block at all, not
    // as an empty one -- ReviewInbox draws one labelled box per top-level key.
    const client = fakeHermes({
      "toee_agent_experience.list_agent_experience": {
        entries: [{ ...L6_PROPOSAL, annotations: {} }],
      },
      "toee_semantic_lexicon.list_lexicon_entries": { entries: [], lexicon_version: null },
      "toee_review_inbox.list_review_items": { items: [], open_count: 0 },
    });

    const body = (await (await handleListInboxViaApi(client)).json()) as {
      items: { kind: string; annotations: Record<string, unknown> | null }[];
    };
    expect(body.items).toHaveLength(1);
    expect(body.items[0]!.annotations).toBeNull();
  });
});
