// Memory Hub aggregate read (0.0.5 S14, FR-21/US9/PAC-5).
//
// The fixture is deliberately UNEVEN: every layer gets a different number, and
// each scoped count has at least one row it must EXCLUDE. A one-row-per-layer
// fixture cannot tell a correct query from one that returns everything -- so the
// L7 store below holds 10 rows of which only 3 are pending, only 5 confirmed and
// only 2 zero-hit-and-confirmed, and `l6_confirmed_entries: 5` in the metrics
// payload differs from the 2 confirmed L6 ROWS so sourcing one from the other
// shows up as a wrong number rather than a coincidence.
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { describe, expect, it } from "vitest";
import { HermesApiClient } from "../../gateway/hermes-api-client";
import {
  handleGetMemoryHubViaApi,
  MEMORY_HUB_UNAVAILABLE,
  type MemoryHubRow,
  type MemoryHubView,
} from "./memory-hub";

type SentDispatch = { tool: string; action: string; params: Record<string, unknown> };

function dispatchResponse(data: unknown): Response {
  return new Response(JSON.stringify({ ok: true, data }), { status: 200 });
}

function governedError(message = "nope"): Response {
  return new Response(
    JSON.stringify({ ok: false, error: { class: "policy_blocked", message } }),
    { status: 200 },
  );
}

// --- fixtures ---------------------------------------------------------------

function experienceRow(id: string, status: string) {
  return {
    id,
    kind: "note",
    status,
    content: `learning ${id}`,
    source: "copilot_agent",
    proposer_context: null,
    decider_account_id: null,
    decided_at: null,
    created_at: "2026-07-01T10:00:00Z",
  };
}

// 4 proposed / 2 confirmed / 1 rejected -- 7 rows, three different answers.
const EXPERIENCE_ENTRIES = [
  experienceRow("exp_p1", "proposed"),
  experienceRow("exp_p2", "proposed"),
  experienceRow("exp_p3", "proposed"),
  experienceRow("exp_p4", "proposed"),
  experienceRow("exp_c1", "confirmed"),
  experienceRow("exp_c2", "confirmed"),
  experienceRow("exp_r1", "rejected"),
];

function lexiconRow(id: string, status: string, hitCount: number, injections = 0) {
  return {
    id,
    domain: "tire",
    entry_kind: "alias",
    surface_form: `sf_${id}`,
    canonical_form: `cf_${id}`,
    status,
    provenance: "admin_manual",
    evidence: null,
    proposer_context: null,
    pii_redacted: false,
    decider_account_id: "seed-supervisor",
    provenance_unattributed: false,
    decided_at: null,
    hit_count: hitCount,
    created_at: "2026-07-01T10:00:00Z",
    updated_at: "2026-07-01T10:00:00Z",
    // 0.0.5 S26: both twins always attach this. `scope` and `basis` are what
    // make the mapper keep the score rather than null it.
    entry_health: {
      score: 0.5,
      scope: "external customer turns only",
      basis: "turn-level attribution",
      usage: { hits: hitCount, injections, saturation: 10 },
      honored: { rate: null, passed: 0, determinate: 0, undetermined: 0 },
      misapplied: { rate: null, passed: 0, determinate: 0, undetermined: 0 },
      stale: { rate: null, passed: 0, determinate: 0, undetermined: 0 },
      weights: { usage: 0.5, honored: 0.5, misapplied: 0.3, stale: 0.2 },
    },
  };
}

// 10 rows: 3 proposed (one of them unused), 5 confirmed, 1 rejected and 1
// retired, both unused. So "count every row" gives 10 and "count every unused
// row" gives 4.
//
// D22 is the reason `lex_c2` exists. `hit_count` counts deterministic-seam
// applications, and the seam only ever applies aliases and normalizers -- so a
// `default_rule` earns exactly zero hits for ever, however well it works.
// `lex_c2` is that row: zero hits, five ledger injections. The old
// `confirmed AND hit_count = 0` count answered 2 and permanently included every
// seasonal default; the effectiveness read answers 1. Regress to hit_count and
// this fixture says 2.
const LEXICON_ENTRIES = [
  lexiconRow("lex_p1", "proposed", 0),
  lexiconRow("lex_p2", "proposed", 4),
  lexiconRow("lex_p3", "proposed", 7),
  lexiconRow("lex_c1", "confirmed", 0, 0),
  lexiconRow("lex_c2", "confirmed", 0, 5),
  lexiconRow("lex_c3", "confirmed", 3, 2),
  lexiconRow("lex_c4", "confirmed", 11, 9),
  lexiconRow("lex_c5", "confirmed", 2, 0),
  lexiconRow("lex_x1", "rejected", 0),
  lexiconRow("lex_x2", "retired", 0),
];

const CORPUS = {
  doc_count: 7,
  chunk_count: 167,
  last_ingest_at: "2026-07-25T04:00:00Z",
  by_type: [{ page_type: "page", count: 7 }],
  last_ingest_job: null,
};

const RETENTION = {
  last_run_at: "2026-07-20T03:00:00.000000+00:00",
  counts: { verified: 3, provisional: 5 },
  total_deleted: 8,
  windows_days: { verified: 730, provisional: 90 },
};

const METRICS = {
  memory_injection: { injected: 11, total: 40, rate: 0.275 },
  knowledge_search: { found: 22, total: 30, rate: 0.7333 },
  // 9 + 4 + 2 + 1 = 16 bindings with at least one slot.
  slots_populated_distribution: { "1": 9, "2": 4, "3": 2, "4": 1 },
  honored_rate: {
    live: false,
    rate: null,
    sample_size: null,
    candidate_total: null,
    undetermined_count: null,
    window_seconds: null,
    as_of: null,
    label: "Not yet computed on this deployment.",
  },
  merge_count: 6,
  correction_count: 12,
  proposal_outcomes: { accepted: 12, dismissed: 4, rate: 0.75 },
  self_service_usage: 2,
  // Deliberately NOT 2 (the confirmed L6 row count): a lifetime count of confirm
  // EVENTS, a different fact. Sourcing the L6 row count from here would read 5.
  l6_confirmed_entries: 5,
};

const PAYLOAD_BY_ACTION: Record<string, unknown> = {
  list_agent_experience: { entries: EXPERIENCE_ENTRIES },
  list_lexicon_entries: { entries: LEXICON_ENTRIES, lexicon_version: null },
  get_corpus_status: CORPUS,
  get_retention_status: RETENTION,
  get_aggregate_metrics: METRICS,
};

// --- harness ----------------------------------------------------------------

/** One fake transport shared by both profile clients; records what was sent. */
function harness(failing: ReadonlySet<string> = new Set()) {
  const sent: SentDispatch[] = [];
  const fetchImpl = async (_url: string, init: RequestInit): Promise<Response> => {
    const body = JSON.parse(init.body as string) as SentDispatch;
    sent.push(body);
    if (failing.has(body.action)) return governedError();
    return dispatchResponse(PAYLOAD_BY_ACTION[body.action]);
  };
  const client = (baseUrl: string) =>
    new HermesApiClient({ baseUrl, token: "tok", actorAccountId: "seed-supervisor", fetchImpl });
  return {
    sent,
    copilot: client("http://copilot.internal"),
    admin: client("http://admin.internal"),
  };
}

async function view(failing?: ReadonlySet<string>): Promise<{
  body: MemoryHubView;
  sent: SentDispatch[];
  status: number;
}> {
  const h = harness(failing);
  const res = await handleGetMemoryHubViaApi(h.copilot, h.admin);
  return { body: (await res.json()) as MemoryHubView, sent: h.sent, status: res.status };
}

function rowFor(body: MemoryHubView, layer: string): MemoryHubRow {
  const row = body.rows.find((r) => r.layer === layer);
  if (!row) throw new Error(`no row for ${layer}`);
  return row;
}

// --- tests ------------------------------------------------------------------

describe("handleGetMemoryHubViaApi", () => {
  // The PII tripwire (NFR-6, and the S14 brief's first hazard): the hub composes
  // EXISTING reads, and this pins WHICH. `get_memory_audit` / `get_preferences`
  // would return L4 slot VALUES -- adding either to make a "richer" row turns an
  // overview page into a per-customer PII surface, and breaks this test.
  // It is also the read-only assertion: every one of these five is a read.
  it("composes exactly the five existing layer reads, and nothing that returns L4 content", async () => {
    const { sent, status } = await view();
    expect(status).toBe(200);
    expect(sent.map((d) => `${d.tool}.${d.action}`).sort()).toEqual([
      "toee_agent_experience.list_agent_experience",
      "toee_knowledge_ops.get_corpus_status",
      "toee_metrics.get_aggregate_metrics",
      "toee_retention.get_retention_status",
      "toee_semantic_lexicon.list_lexicon_entries",
    ]);
    // No filters: an unscoped list is what makes the counts whole-store counts.
    for (const d of sent) expect(d.params).toEqual({});
  });

  it("carries one row per layer L1-L7 in the memory-layers.md order, each with the doc's label", async () => {
    const { body } = await view();
    expect(body.rows.map((r) => r.layer)).toEqual(["L1", "L2", "L3", "L4", "L5", "L6", "L7"]);
    expect(body.rows.map((r) => r.name)).toEqual([
      "Identity Graph",
      "Conversation",
      "Operational",
      "Customer Memory",
      "Knowledge",
      "Agent experience",
      "Semantic lexicon",
    ]);
    // memory-layers.md's at-a-glance Status column: all seven are shipped.
    expect(body.rows.every((r) => r.status === "shipped")).toBe(true);
  });

  it("deep-links every layer that has a console, and links nothing it does not have", async () => {
    const { body } = await view();
    expect(body.rows.map((r) => r.href)).toEqual([
      null,
      "/copilot",
      "/copilot/audit/auto-handled",
      "/admin/memory-audit",
      "/admin/knowledge",
      "/admin/agent-experience",
      "/admin/lexicon",
    ]);
  });

  // The scoping test. 10 L7 rows in the fixture; three different right answers,
  // each excluding rows a naive query would include.
  it("scopes the L7 counts, and says in each label what the number is scoped to", async () => {
    const { body } = await view();
    expect(rowFor(body, "L7").counts).toEqual([
      { label: "Pending proposals (status = proposed)", value: "3" },
      {
        label:
          "Confirmed entries in the store — NOT what a turn carries: the prompt " +
          "glossary is a bounded window (LEXICON_GLOSSARY_LIMIT) filled " +
          "newest-first by default or health-ranked when LEXICON_SELECTION=health, " +
          "and off-season default_rule rows are dropped at render",
        value: "5",
      },
      {
        label:
          "Confirmed entries with no recorded use — no deterministic-seam hit " +
          "(lifetime) AND no prompt injection in the ledger's retention window. " +
          "Reads entry_effectiveness, not hit_count alone: hit_count is " +
          "structurally zero for every default_rule, so a hit-only count would " +
          "permanently include every seasonal rule (D22)",
        value: "1",
      },
    ]);
  });

  // D22, as its own assertion rather than only as a number in the list above:
  // the row that separates the two readings is a confirmed entry with zero
  // lifetime hits and real ledger usage. Counting it is what would have fed
  // every seasonal default_rule to a zero-hit retirement queue.
  it("does not call an entry unused when the ledger says it reached prompts (D22)", async () => {
    const { body } = await view();
    const unused = rowFor(body, "L7").counts[2];
    expect(unused?.value).toBe("1");
    // Sanity that the fixture still separates the two readings: 2 confirmed
    // rows have hit_count 0, so a regression to the old query reads "2".
    expect(
      LEXICON_ENTRIES.filter((e) => e.status === "confirmed" && e.hit_count === 0),
    ).toHaveLength(2);
  });

  // Found by running this against the live stack: its dispatch image predates
  // the effectiveness score, so every entry arrived with `entry_health` absent
  // -- and the tile answered "0 with no recorded use" when the truth was "with
  // no effectiveness data, nobody can say". A zero there is the exact defect
  // this hub's `{label, value}` shape exists to prevent, so the third state gets
  // used: unavailable.
  it("says unavailable, not 0, when a confirmed entry arrived with no effectiveness score", async () => {
    const noHealth = LEXICON_ENTRIES.map(({ entry_health: _h, ...rest }) => rest);
    const fetchImpl = async (_url: string, init: RequestInit): Promise<Response> => {
      const sent = JSON.parse(init.body as string) as SentDispatch;
      return dispatchResponse(
        sent.action === "list_lexicon_entries"
          ? { entries: noHealth, lexicon_version: null }
          : PAYLOAD_BY_ACTION[sent.action],
      );
    };
    const client = (baseUrl: string) =>
      new HermesApiClient({ baseUrl, token: "tok", actorAccountId: "seed-supervisor", fetchImpl });
    const res = await handleGetMemoryHubViaApi(
      client("http://copilot.internal"),
      client("http://admin.internal"),
    );
    const body = (await res.json()) as MemoryHubView;
    expect(rowFor(body, "L7").counts[2]?.value).toBe(MEMORY_HUB_UNAVAILABLE);
    // ... and the two counts that do not depend on the score still render.
    expect(rowFor(body, "L7").counts[0]?.value).toBe("3");
    expect(rowFor(body, "L7").counts[1]?.value).toBe("5");
  });

  // The same class on the sibling path: L6's injection is bounded newest-first
  // too, so its confirmed count is no more "what the prompt carries" than L7's.
  it("scopes the L6 counts the same way, bound included", async () => {
    const { body } = await view();
    expect(rowFor(body, "L6").counts).toEqual([
      { label: "Pending proposals (status = proposed)", value: "4" },
      {
        label:
          "Confirmed entries in the store — NOT what a turn carries: injection is " +
          "a bounded newest-first window",
        value: "2",
      },
    ]);
  });

  it("gives L4 counts only, with the scope of each spelled out and no customer content", async () => {
    const { body } = await view();
    const l4 = rowFor(body, "L4");
    expect(l4.counts).toEqual([
      {
        label:
          "Customer bindings with at least one slot — a provisional and a verified " +
          "binding for the same person count separately",
        value: "16",
      },
      { label: "Last retention sweep (UTC)", value: "2026-07-20T03:00:00.000Z" },
      {
        label: "Slots that sweep deleted (verified 3 / provisional 5)",
        value: "8",
      },
    ]);
    expect(l4.note).toMatch(/PII/);
    // Nothing customer-shaped may ride along: the hub reads counts, never slots.
    expect(JSON.stringify(l4)).not.toMatch(/binding_key|slot_value|provisional:/);
  });

  it("gives L5 the corpus counts, the last ingest, and a found rate labelled as lifetime", async () => {
    const { body } = await view();
    expect(rowFor(body, "L5").counts).toEqual([
      { label: "Corpus documents", value: "7" },
      { label: "Corpus chunks", value: "167" },
      { label: "Last ingest (UTC)", value: "2026-07-25T04:00:00.000Z" },
      {
        label:
          "Knowledge found rate — every search ever recorded (a lifetime " +
          "metric_event total, not a window)",
        value: "73.3% (22 / 30)",
      },
    ]);
  });

  // A zero here would read as "nothing happened on L1-L3", which is a different
  // claim from "this hub has no read that counts it".
  it("reports no live count for L1-L3 rather than a zero that would read as none", async () => {
    const { body } = await view();
    for (const layer of ["L1", "L2", "L3"]) {
      const row = rowFor(body, layer);
      expect(row.counts).toEqual([]);
      expect(row.note).toMatch(/no live count/i);
    }
  });

  it("reports a failed source as unavailable rather than zero, and still renders the other layers", async () => {
    const { body, status } = await view(new Set(["list_lexicon_entries"]));
    expect(status).toBe(200);
    expect(rowFor(body, "L7").counts.map((c) => c.value)).toEqual([
      MEMORY_HUB_UNAVAILABLE,
      MEMORY_HUB_UNAVAILABLE,
      MEMORY_HUB_UNAVAILABLE,
    ]);
    // The label survives the failure -- an unlabelled "unavailable" would be as
    // uninformative as an unlabelled number.
    expect(rowFor(body, "L7").counts[0]?.label).toMatch(/Pending proposals/);
    // L6 came from a different dispatch and is unaffected.
    expect(rowFor(body, "L6").counts.map((c) => c.value)).toEqual(["4", "2"]);
  });

  // The hub shows two fields out of the metrics payload. Validating the WHOLE
  // metrics contract here would mean any tile another slice adds -- S18's
  // `latency` block landed mid-flight in this very checkout -- blanks the L4 and
  // L5 counts on a page that never renders it. This pins the narrow read: a
  // payload with only the two fields the hub uses still produces both numbers.
  it("reads only the two metrics fields it renders, so another slice's new tile cannot blank L4/L5", async () => {
    const minimal = async (_url: string, init: RequestInit): Promise<Response> => {
      const body = JSON.parse(init.body as string) as SentDispatch;
      if (body.action === "get_aggregate_metrics") {
        return dispatchResponse({
          slots_populated_distribution: { "1": 9, "2": 4, "3": 2, "4": 1 },
          knowledge_search: { found: 22, total: 30, rate: 0.7333 },
        });
      }
      return dispatchResponse(PAYLOAD_BY_ACTION[body.action]);
    };
    const client = (baseUrl: string) =>
      new HermesApiClient({ baseUrl, token: "tok", actorAccountId: "a", fetchImpl: minimal });
    const res = await handleGetMemoryHubViaApi(
      client("http://copilot.internal"),
      client("http://admin.internal"),
    );
    const body = (await res.json()) as MemoryHubView;
    expect(rowFor(body, "L4").counts[0]?.value).toBe("16");
    expect(rowFor(body, "L5").counts[3]?.value).toBe("73.3% (22 / 30)");
  });

  // "The doc and the UI stay twins" is the slice's own claim, and the page repeats
  // it on screen. Read the doc rather than a second hardcoded list: a restatement
  // of the thing under test only fires when someone edits BOTH, which is the one
  // case that needs no test (D17b's lesson from tools.test.ts). This fires when
  // memory-layers.md renames or reorders a layer and nobody mirrors it here.
  it("takes its layer ids and names from memory-layers.md's at-a-glance table", async () => {
    // Walk up from the cwd rather than skipping when the file is not where this
    // test guessed: a lookup that silently no-ops is how a tripwire dies.
    let dir = process.cwd();
    let docPath: string | null = null;
    for (let i = 0; i < 6 && docPath === null; i += 1) {
      const candidate = join(dir, "docs", "architecture", "memory-layers.md");
      if (existsSync(candidate)) docPath = candidate;
      dir = dirname(dir);
    }
    if (docPath === null) throw new Error(`memory-layers.md not found from ${process.cwd()}`);
    const md = readFileSync(docPath, "utf8");
    // Scoped to the at-a-glance SECTION, which is what this test says it reads.
    // The unscoped scrape matched any table row whose first cell was a bare
    // layer id, so 0.0.5 S22's forgetting table -- which needs several rows per
    // layer -- broke it by existing. Narrowing to the section keeps exactly the
    // drift this fires on (a layer renamed or reordered in the table the hub
    // mirrors) and stops unrelated tables from deciding the answer. The section
    // slice is asserted below, so a renamed heading fails loudly rather than
    // silently yielding zero rows.
    const start = md.indexOf("## At a glance");
    expect(start, "memory-layers.md lost its '## At a glance' heading").toBeGreaterThan(-1);
    const rest = md.slice(start + 1);
    const glance = rest.slice(0, rest.indexOf("\n## "));
    const documented = [
      ...glance.matchAll(/^\|\s*\*{0,2}(L[1-7])\*{0,2}\s*\|\s*([^|]+?)\s*\|/gm),
    ].map((m) => ({ layer: String(m[1]), name: String(m[2]).replace(/\*/g, "").trim() }));
    expect(documented).toHaveLength(7);

    const { body } = await view();
    expect(body.rows.map((r) => ({ layer: r.layer, name: r.name }))).toEqual(documented);
  });

  it("says 'never' rather than inventing a date when a sweep or ingest has not run", async () => {
    const h = harness();
    const never = async (_url: string, init: RequestInit): Promise<Response> => {
      const body = JSON.parse(init.body as string) as SentDispatch;
      if (body.action === "get_retention_status") {
        return dispatchResponse({ ...RETENTION, last_run_at: null, total_deleted: 0 });
      }
      if (body.action === "get_corpus_status") {
        return dispatchResponse({ ...CORPUS, last_ingest_at: null });
      }
      return dispatchResponse(PAYLOAD_BY_ACTION[body.action]);
    };
    const client = (baseUrl: string) =>
      new HermesApiClient({ baseUrl, token: "tok", actorAccountId: "a", fetchImpl: never });
    void h;
    const res = await handleGetMemoryHubViaApi(
      client("http://copilot.internal"),
      client("http://admin.internal"),
    );
    const body = (await res.json()) as MemoryHubView;
    expect(rowFor(body, "L4").counts[1]).toEqual({
      label: "Last retention sweep (UTC)",
      value: "never",
    });
    expect(rowFor(body, "L5").counts[2]).toEqual({
      label: "Last ingest (UTC)",
      value: "never",
    });
  });
});
