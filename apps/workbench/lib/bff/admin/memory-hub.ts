// Memory Hub aggregate read (0.0.5 S14, FR-21 / US9 / PAC-5) for the Admin BFF
// (ADR-0093 admin route group). One row per memory layer L1-L7, mirroring the
// at-a-glance table of `docs/architecture/memory-layers.md` -- the architecture
// diagram AS the UI, with live numbers and a deep link into each layer's console.
//
// NO new Hermes action. This composes the FIVE reads that already exist, through
// the same two profile clients their own routes use: `toee_agent_experience`,
// `toee_semantic_lexicon`, `toee_retention` and `toee_metrics` are allowlisted
// for internal_copilot; `toee_knowledge_ops` goes over the Supervisor Admin
// profile, exactly as admin/knowledge.ts does. Nothing new is registered, so
// NFR-9 catalog-sync has nothing to mirror and nothing here is LLM-callable.
//
// READ-ONLY: every dispatch is `dispatch`, never `dispatchWrite`. The page has no
// action, so it needs no ADR-0148 governed-action treatment.
//
// Two rules this module exists to keep, both of which a "just show the numbers"
// hub would break:
//
//  1. L4 is the per-customer PII layer by design (NFR-6). The hub shows COUNTS
//     and layer metadata only. It deliberately does NOT dispatch
//     `get_memory_audit` / `get_preferences`, which return slot values;
//     memory-hub.test.ts pins the dispatched set so adding one is a red test.
//  2. A count that silently means something narrower than its label is the
//     failure mode here, so a count NEVER travels without its scope. That is why
//     the wire type is a `{label, value}` pair rather than a bare number: there
//     is no shape in which a renderer can show "L7: 34" with the caveat lost.
//     The standing example is L7's own glossary -- the store may hold 34
//     confirmed entries while the prompt carries a bounded window of
//     LEXICON_GLOSSARY_LIMIT (20) of them, and L6's injection is bounded the same
//     way. Neither confirmed count is "what the model sees", and both labels say
//     so. Since 0.0.5 S26 the L7 label also names WHICH 20: newest-first by
//     default, health-ranked once LEXICON_SELECTION is flipped.
import { ROUTES } from "@toee/shared";
import {
  HermesApiError,
  type HermesApiClient,
} from "../../gateway/hermes-api-client";
import type { AgentExperienceEntry, LexiconEntry } from "../../gateway/types";
import { json } from "../respond";
import { mapAgentExperienceEntry } from "./agent-experience";
import { mapCorpusStatus, type CorpusStatus } from "./knowledge";
import { mapRetentionStatus, type RetentionStatus } from "./retention";
import { mapLexiconEntry } from "./semantic-lexicon";

/** A number and the exact thing it counts. Never one without the other. */
export interface MemoryHubCount {
  label: string;
  value: string;
}

export interface MemoryHubRow {
  layer: string;
  name: string;
  holds: string;
  status: string;
  /** The layer's console, or null when it has none. */
  href: string | null;
  counts: MemoryHubCount[];
  note: string | null;
}

export interface MemoryHubView {
  rows: MemoryHubRow[];
}

// Not "0", and not a missing row: a read that failed is a third state, and
// collapsing it into a zero is the same lie as an under-scoped label.
export const MEMORY_HUB_UNAVAILABLE = "unavailable";

// Layer-agnostic shorthand: the value when its source did not load.
function counted(value: number | string | null, label: string): MemoryHubCount {
  return { label, value: value === null ? MEMORY_HUB_UNAVAILABLE : String(value) };
}

/** ISO in, normalized UTC ISO out; `null` becomes an honest "never". */
function at(iso: string | null | undefined, source: unknown): string {
  if (source === null) return MEMORY_HUB_UNAVAILABLE;
  if (!iso) return "never";
  const ms = Date.parse(iso);
  return Number.isNaN(ms) ? iso : new Date(ms).toISOString();
}

function ratePct(rate: number | null, found: number, total: number): string {
  if (rate === null) return `— (${found} / ${total})`;
  return `${Math.round(rate * 1000) / 10}% (${found} / ${total})`;
}

// Any failure of ONE source degrades that layer's counts to "unavailable"; the
// other six rows still render. A hub that 502s because the corpus read hiccuped
// would hide the six layers that are fine. The mappers are reused rather than
// re-implemented, so a malformed upstream is caught here too -- and reads
// "unavailable", never a partially-parsed number.
async function read<T>(load: () => Promise<T>): Promise<T | null> {
  try {
    return await load();
  } catch {
    return null;
  }
}

function entriesOf(data: unknown): unknown[] {
  const d = (data ?? {}) as Record<string, unknown>;
  return Array.isArray(d.entries) ? (d.entries as unknown[]) : [];
}

// The hub reads TWO fields out of the aggregate-metrics payload, so it maps those
// two rather than reusing `mapAggregateMetrics`. That mapper validates the WHOLE
// metrics-panel contract, which grows with every tile another slice adds (S18's
// `latency` block is the current example) -- and a field this page never displays
// must not be able to turn the L4 and L5 counts into "unavailable". The rule
// followed elsewhere in this file is the other half of the same principle: the
// corpus / retention / entry mappers ARE reused, because their validation covers
// the fields the hub actually uses.
interface HubMetrics {
  bindingsWithASlot: number;
  knowledgeFound: number;
  knowledgeTotal: number;
  knowledgeRate: number | null;
}

function num(value: unknown, field: string): number {
  if (typeof value !== "number" || Number.isNaN(value)) {
    throw new HermesApiError("unexpected_error", `malformed aggregate metrics: ${field}`);
  }
  return value;
}

function mapHubMetrics(raw: unknown): HubMetrics {
  if (typeof raw !== "object" || raw === null) {
    throw new HermesApiError("unexpected_error", "malformed aggregate metrics payload");
  }
  const r = raw as Record<string, unknown>;
  const dist = r.slots_populated_distribution;
  const search = r.knowledge_search;
  if (typeof dist !== "object" || dist === null) {
    throw new HermesApiError(
      "unexpected_error",
      "malformed aggregate metrics: slots_populated_distribution",
    );
  }
  if (typeof search !== "object" || search === null) {
    throw new HermesApiError(
      "unexpected_error",
      "malformed aggregate metrics: knowledge_search",
    );
  }
  const d = dist as Record<string, unknown>;
  const s = search as Record<string, unknown>;
  const rate = s.rate;
  return {
    bindingsWithASlot: (["1", "2", "3", "4"] as const).reduce(
      (sum, key) => sum + num(d[key], `slots_populated_distribution.${key}`),
      0,
    ),
    knowledgeFound: num(s.found, "knowledge_search.found"),
    knowledgeTotal: num(s.total, "knowledge_search.total"),
    knowledgeRate: rate === null ? null : num(rate, "knowledge_search.rate"),
  };
}

interface Sources {
  experience: AgentExperienceEntry[] | null;
  lexicon: LexiconEntry[] | null;
  corpus: CorpusStatus | null;
  retention: RetentionStatus | null;
  metrics: HubMetrics | null;
}

function tally<T>(rows: T[] | null, predicate: (row: T) => boolean): number | null {
  return rows === null ? null : rows.filter(predicate).length;
}

function buildMemoryHubRows(sources: Sources): MemoryHubRow[] {
  const { experience, lexicon, corpus, retention, metrics } = sources;

  const bindingsWithASlot = metrics === null ? null : metrics.bindingsWithASlot;

  return [
    {
      layer: "L1",
      name: "Identity Graph",
      holds:
        "channel identities, identity snapshots, Shopify/cross-system links, consent, match history",
      status: "shipped",
      href: null,
      counts: [],
      note:
        "No live count on this hub and no console of its own: nothing in the admin " +
        "surface reads this layer in aggregate today. Stated rather than shown as a zero.",
    },
    {
      layer: "L2",
      name: "Conversation",
      holds: "Customer/Email threads, SMS session windows, MessageTurn, AgentTurnContext",
      status: "shipped",
      href: ROUTES.copilot,
      counts: [],
      note:
        "No live count on this hub: thread volume is per-case in the Copilot workbench, " +
        "and no aggregate read exposes it.",
    },
    {
      layer: "L3",
      name: "Operational",
      holds: "Follow-up Cases, Workbench Audit Log, auto-handled evidence, eval records",
      status: "shipped",
      href: ROUTES.copilotAuditAutoHandled,
      counts: [],
      note:
        "No live count on this hub: the audit and eval consoles list their own rows, " +
        "and no aggregate read counts them.",
    },
    {
      layer: "L4",
      name: "Customer Memory",
      holds: "4 governed preference slots per customer",
      status: "shipped",
      href: ROUTES.adminMemoryAudit,
      counts: [
        counted(
          bindingsWithASlot,
          "Customer bindings with at least one slot — a provisional and a verified " +
            "binding for the same person count separately",
        ),
        {
          label: "Last retention sweep (UTC)",
          value: at(retention?.lastRunAt, retention),
        },
        {
          label:
            retention === null
              ? "Slots that sweep deleted"
              : `Slots that sweep deleted (verified ${retention.counts.verified} / provisional ${retention.counts.provisional})`,
          value: retention === null ? MEMORY_HUB_UNAVAILABLE : String(retention.totalDeleted),
        },
      ],
      note:
        "Counts only. L4 is the per-customer PII layer by design (NFR-6), so no slot " +
        "value, binding key or customer identifier is read by this page — open Memory " +
        "Audit for one named case instead.",
    },
    {
      layer: "L5",
      name: "Knowledge",
      holds: "shared, non-PII company/product corpus (separate toee_knowledge DB)",
      status: "shipped",
      href: ROUTES.adminKnowledge,
      counts: [
        counted(corpus === null ? null : corpus.docCount, "Corpus documents"),
        counted(corpus === null ? null : corpus.chunkCount, "Corpus chunks"),
        { label: "Last ingest (UTC)", value: at(corpus?.lastIngestAt, corpus) },
        {
          label:
            "Knowledge found rate — every search ever recorded (a lifetime " +
            "metric_event total, not a window)",
          value:
            metrics === null
              ? MEMORY_HUB_UNAVAILABLE
              : ratePct(
                  metrics.knowledgeRate,
                  metrics.knowledgeFound,
                  metrics.knowledgeTotal,
                ),
        },
      ],
      note: null,
    },
    {
      layer: "L6",
      name: "Agent experience",
      holds: "what the agent learns from doing the job (operational, non-PII)",
      status: "shipped",
      href: ROUTES.adminAgentExperience,
      counts: [
        counted(
          tally(experience, (e) => e.status === "proposed"),
          "Pending proposals (status = proposed)",
        ),
        counted(
          tally(experience, (e) => e.status === "confirmed"),
          "Confirmed entries in the store — NOT what a turn carries: injection is " +
            "a bounded newest-first window",
        ),
      ],
      note: null,
    },
    {
      layer: "L7",
      name: "Semantic lexicon",
      holds: "domain language: aliases, notation normalizers, contextual defaults (shared, non-PII)",
      status: "shipped",
      href: ROUTES.adminLexicon,
      counts: [
        counted(
          tally(lexicon, (e) => e.status === "proposed"),
          "Pending proposals (status = proposed)",
        ),
        counted(
          tally(lexicon, (e) => e.status === "confirmed"),
          "Confirmed entries in the store — NOT what a turn carries: the prompt " +
            "glossary is a bounded window (LEXICON_GLOSSARY_LIMIT) filled " +
            "newest-first by default or health-ranked when LEXICON_SELECTION=health, " +
            "and off-season default_rule rows are dropped at render",
        ),
        counted(
          // 0.0.5 S22 / D22. This used to be `confirmed AND hitCount === 0`,
          // and that reading is knowably misleading: `hit_count` counts
          // DETERMINISTIC-SEAM applications, and the seam only ever applies
          // `alias` and `normalizer` rows. A `default_rule` renders into the
          // prompt as an imperative ask and is never "applied", so it earns
          // exactly zero hits for ever, however well it works -- which put
          // every seasonal default permanently inside this count. The same
          // finding is why FR-20's retirement feed reads effectiveness too.
          //
          // The effectiveness read answers the question the label asks: hits
          // (lifetime, S05's rollup) AND ledger injections (windowed by the
          // ledger's own retention) both zero. Both halves matter -- an entry
          // reaching prompts with no seam applications is USED, and an entry
          // with old hits and no recent injections is the retirement candidate.
          //
          // An entry whose health did not survive the mapper (no scope, no
          // basis -- S26's refusal) is left OUT of the count rather than
          // guessed at: a score whose meaning was lost cannot answer this.
          tally(
            lexicon,
            (e) =>
              e.status === "confirmed" &&
              e.health !== null &&
              e.health.usage.hits === 0 &&
              e.health.usage.injections === 0,
          ),
          "Confirmed entries with no recorded use — no deterministic-seam hit " +
            "(lifetime) AND no prompt injection in the ledger's retention window. " +
            "Reads entry_effectiveness, not hit_count alone: hit_count is " +
            "structurally zero for every default_rule, so a hit-only count would " +
            "permanently include every seasonal rule (D22)",
        ),
      ],
      note: null,
    },
  ];
}

export async function handleGetMemoryHubViaApi(
  copilot: HermesApiClient,
  admin: HermesApiClient,
): Promise<Response> {
  const [experience, lexicon, corpus, retention, metrics] = await Promise.all([
    read(async () =>
      entriesOf(
        await copilot.dispatch("toee_agent_experience", "list_agent_experience", {}),
      ).map(mapAgentExperienceEntry),
    ),
    read(async () =>
      entriesOf(
        await copilot.dispatch("toee_semantic_lexicon", "list_lexicon_entries", {}),
      ).map(mapLexiconEntry),
    ),
    read(async () =>
      mapCorpusStatus(await admin.dispatch("toee_knowledge_ops", "get_corpus_status", {})),
    ),
    read(async () =>
      mapRetentionStatus(await copilot.dispatch("toee_retention", "get_retention_status", {})),
    ),
    read(async () =>
      mapHubMetrics(await copilot.dispatch("toee_metrics", "get_aggregate_metrics", {})),
    ),
  ]);

  return json({
    rows: buildMemoryHubRows({ experience, lexicon, corpus, retention, metrics }),
  } satisfies MemoryHubView);
}
