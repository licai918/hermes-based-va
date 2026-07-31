// L7 Semantic Lexicon admin surface (0.0.5 S02, FR-3 decide side / FR-8) for the
// Admin BFF (ADR-0093 admin route group). Pure and dependency-injected like the
// sibling admin/*.ts modules; the thin app/api/admin/lexicon routes wrap these
// with withSession + a per-profile client. Direct sibling of
// admin/agent-experience.ts -- L6's console is the skeleton this mirrors.
//
// Dispatches over the Internal Copilot Profile API (HERMES_COPILOT_API_URL/
// TOKEN), NOT the Supervisor Admin Profile API: toee_semantic_lexicon is
// allowlisted for internal_copilot only (hermes/toee_hermes/plugin/profiles.py),
// the same reason admin/agent-experience.ts reaches that profile. Admin-gating
// (ADR-0093) still comes from the BFF route itself (/api/admin/* +
// withSession's role check), not from which Hermes profile answers.
//
// READS use `dispatch` (fail-open on actor); every WRITE uses `dispatchWrite`,
// which refuses before the network call when no acting account is configured.
// That is defense-in-depth in front of the Hermes-side gate: D20 makes an
// unattributed admin action a fail-closed policy_blocked on the server too,
// because `admin_manual` with no decider is unfalsifiable provenance.
import type { HermesAgentClient } from "../../gateway/hermes-agent-client";
import type { HermesApiClient } from "../../gateway/hermes-api-client";
import { HermesApiError } from "../../gateway/hermes-api-client";
import { hermesErrorToProblem } from "../../gateway/hermes-error";
import type {
  LexiconEntry,
  LexiconEntryHealth,
  LexiconEntryKind,
  LexiconHealthLeg,
  LexiconProvenance,
  LexiconStatus,
} from "../../gateway/types";
import { json, problem } from "../respond";

const TOOL = "toee_semantic_lexicon";

const KINDS: readonly LexiconEntryKind[] = ["alias", "normalizer", "default_rule"];
const STATUSES: readonly LexiconStatus[] = [
  "proposed",
  "confirmed",
  "rejected",
  "retired",
];
const PROVENANCES: readonly LexiconProvenance[] = [
  "admin_manual",
  "conversation_confirmed",
  "feedback_derived",
];

// The three decisions and the edit, keyed by the URL segment the route uses.
export const LEXICON_DECISION_ACTIONS = {
  confirm: "confirm_lexicon_entry",
  reject: "reject_lexicon_entry",
  retire: "retire_lexicon_entry",
} as const;

export type LexiconDecision = keyof typeof LEXICON_DECISION_ACTIONS;

function isoToMsOrNull(value: unknown): number | null {
  if (typeof value !== "string") return null;
  const ms = Date.parse(value);
  return Number.isNaN(ms) ? null : ms;
}

function str(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function num(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function leg(raw: unknown): LexiconHealthLeg {
  const r = (raw ?? {}) as Record<string, unknown>;
  return {
    // A null rate is the honest "this leg has no denominator". Coercing it to 0
    // would draw a leg nobody scored as a leg that scored perfectly.
    rate: typeof r.rate === "number" && Number.isFinite(r.rate) ? r.rate : null,
    passed: num(r.passed),
    determinate: num(r.determinate),
    undetermined: num(r.undetermined),
  };
}

// 0.0.5 S26 (FR-31). `scope` and `basis` are required, not optional: they are the
// caveats that make the score readable, and a payload without them is a score
// whose meaning was lost in transit -- so it maps to null rather than to a bare
// number. Same stance as the Memory Hub's counted() helper, which will not let a
// count travel without its label.
function mapHealth(raw: unknown): LexiconEntryHealth | null {
  if (typeof raw !== "object" || raw === null) return null;
  const r = raw as Record<string, unknown>;
  if (typeof r.score !== "number" || !Number.isFinite(r.score)) return null;
  if (!str(r.scope) || !str(r.basis)) return null;
  const usage = (r.usage ?? {}) as Record<string, unknown>;
  const weights = (r.weights ?? {}) as Record<string, unknown>;
  return {
    score: r.score,
    scope: str(r.scope),
    basis: str(r.basis),
    usage: {
      hits: num(usage.hits),
      injections: num(usage.injections),
      saturation: num(usage.saturation),
    },
    honored: leg(r.honored),
    misapplied: leg(r.misapplied),
    stale: leg(r.stale),
    weights: {
      usage: num(weights.usage),
      honored: num(weights.honored),
      misapplied: num(weights.misapplied),
      stale: num(weights.stale),
    },
  };
}

export function mapLexiconEntry(raw: unknown): LexiconEntry {
  if (typeof raw !== "object" || raw === null) {
    throw new HermesApiError("unexpected_error", "malformed semantic_lexicon payload");
  }
  const r = raw as Record<string, unknown>;

  const id = r.id;
  if (typeof id !== "string" || id.length === 0) {
    throw new HermesApiError("unexpected_error", "missing semantic_lexicon id");
  }
  const kind = r.entry_kind;
  if (!(KINDS as readonly unknown[]).includes(kind)) {
    throw new HermesApiError(
      "unexpected_error",
      `unknown semantic_lexicon entry_kind: ${String(kind)}`,
    );
  }
  const status = r.status;
  if (!(STATUSES as readonly unknown[]).includes(status)) {
    throw new HermesApiError(
      "unexpected_error",
      `unknown semantic_lexicon status: ${String(status)}`,
    );
  }
  const provenance = r.provenance;
  if (!(PROVENANCES as readonly unknown[]).includes(provenance)) {
    throw new HermesApiError(
      "unexpected_error",
      `unknown semantic_lexicon provenance: ${String(provenance)}`,
    );
  }
  const createdAt = isoToMsOrNull(r.created_at);
  if (createdAt === null) {
    throw new HermesApiError("unexpected_error", "malformed semantic_lexicon created_at");
  }

  const deciderAccountId =
    typeof r.decider_account_id === "string" && r.decider_account_id
      ? r.decider_account_id
      : null;

  return {
    id,
    domain: str(r.domain),
    entryKind: kind as LexiconEntryKind,
    surfaceForm: str(r.surface_form),
    canonicalForm: str(r.canonical_form),
    status: status as LexiconStatus,
    provenance: provenance as LexiconProvenance,
    evidence: typeof r.evidence === "string" ? r.evidence : null,
    proposerContext:
      r.proposer_context && typeof r.proposer_context === "object"
        ? (r.proposer_context as Record<string, unknown>)
        : null,
    // NOT "this row is PII-free" -- see the console's footnote and D2's keep
    // exemption. True means a span WAS removed; false means none was removed,
    // which is a different claim.
    piiRedacted: r.pii_redacted === true,
    deciderAccountId,
    // Derived server-side by the ONE shared helper both Hermes twins call
    // (lexicon_provenance_unattributed). Trusting the server's derivation rather
    // than re-deriving it here keeps a single definition of the D20 sweep.
    provenanceUnattributed: r.provenance_unattributed === true,
    decidedAt: isoToMsOrNull(r.decided_at),
    hitCount: typeof r.hit_count === "number" ? r.hit_count : 0,
    createdAt,
    updatedAt: isoToMsOrNull(r.updated_at),
    health: mapHealth(r.entry_health),
  };
}

// `lexicon_version`, not `confirmed_set_version` (S02 review finding F): the
// server derives it as MAX(updated_at) over the WHOLE table, so a reject moves
// it although the confirmed set did not change. The computation is right -- a
// max scoped to the confirmed rows would go DOWN on a retire, which is what a
// cache must never see -- so the name is what changed.
function mapEntries(data: unknown): { entries: LexiconEntry[]; version: string | null } {
  const d = (data ?? {}) as Record<string, unknown>;
  const rawEntries = Array.isArray(d.entries) ? (d.entries as unknown[]) : [];
  return {
    entries: rawEntries.map(mapLexiconEntry),
    version: typeof d.lexicon_version === "string" ? d.lexicon_version : null,
  };
}

// S01 shipped `list_lexicon_entries` because its acceptance needed a read; S02
// EXTENDED it with the queue filters rather than adding a second read action, so
// the queue and the CRUD list are the same governed surface.
export async function handleListLexiconViaApi(
  client: HermesApiClient,
  filters: { status?: string; domain?: string } = {},
): Promise<Response> {
  const params: Record<string, unknown> = {};
  if (filters.status) params.status = filters.status;
  if (filters.domain) params.domain = filters.domain;
  try {
    const { entries, version } = mapEntries(
      await client.dispatch(TOOL, "list_lexicon_entries", params),
    );
    return json({ entries, lexiconVersion: version });
  } catch (err) {
    return hermesErrorToProblem(err);
  }
}

export async function handleDecideLexiconViaApi(
  client: HermesApiClient,
  decision: LexiconDecision,
  id: string,
): Promise<Response> {
  try {
    const data = await client.dispatchWrite(TOOL, LEXICON_DECISION_ACTIONS[decision], {
      id,
    });
    return json({ entry: mapLexiconEntry(data) });
  } catch (err) {
    return hermesErrorToProblem(err);
  }
}

// A request the BFF can already see is malformed is a 400 here, NOT a dispatch.
// Hermes classifies a blank required field as `unexpected_error`, which the
// house error map (correctly, for an unclassified governed failure) turns into
// 502 -- so a blank Domain in the add form rendered to the admin as "502 Bad
// Gateway". The honest level for "you left a required field empty" is the layer
// that owns the request shape, which is this one; the Hermes-side validator
// stays exactly as it is, as the guard for every other caller.
function requireFields(
  body: Record<string, string | undefined>,
): Response | null {
  for (const [name, value] of Object.entries(body)) {
    if (typeof value !== "string" || value.trim().length === 0) {
      return problem(400, `${name} is required`);
    }
  }
  return null;
}

// D7: an in-place UPDATE of the mapping; the entry id is stable and `hit_count`
// continues. Only the fields the caller actually supplied are forwarded, so an
// omitted field means "leave unchanged" rather than "clear".
export async function handleEditLexiconViaApi(
  client: HermesApiClient,
  id: string,
  body: { surfaceForm?: string; canonicalForm?: string },
): Promise<Response> {
  const params: Record<string, unknown> = { id };
  if (body.surfaceForm !== undefined) params.surface_form = body.surfaceForm;
  if (body.canonicalForm !== undefined) params.canonical_form = body.canonicalForm;
  // An edit that changes nothing would otherwise be a 502 as well.
  if (Object.keys(params).length === 1) {
    return problem(400, "surfaceForm or canonicalForm is required");
  }
  try {
    const data = await client.dispatchWrite(TOOL, "edit_lexicon_entry", params);
    return json({ entry: mapLexiconEntry(data) });
  } catch (err) {
    return hermesErrorToProblem(err);
  }
}

// FR-8/US1: the admin adds "TOEE = TOEE TIRE" and it is live, no deploy. Lands
// `confirmed` + `admin_manual` server-side -- the admin IS the gate, so there is
// no proposal step to approve afterwards.
export async function handleAddLexiconViaApi(
  client: HermesApiClient,
  body: {
    domain?: string;
    entryKind?: string;
    surfaceForm?: string;
    canonicalForm?: string;
    evidence?: string;
    proposerContext?: Record<string, unknown>;
  },
): Promise<Response> {
  const missing = requireFields({
    domain: body.domain,
    entryKind: body.entryKind,
    surfaceForm: body.surfaceForm,
    canonicalForm: body.canonicalForm,
  });
  if (missing) return missing;
  const params: Record<string, unknown> = {
    domain: body.domain,
    entry_kind: body.entryKind,
    surface_form: body.surfaceForm,
    canonical_form: body.canonicalForm,
  };
  if (body.evidence) params.evidence = body.evidence;
  // 0.0.5 S17 (FR-24): the NL prefill's own record, on the param the shared
  // `read_lexicon_proposal` already reads and D2 already scans -- no schema
  // change, no new governed action. Absent for a hand-typed entry, which is
  // exactly what makes "this value started as a machine's suggestion"
  // answerable from the row. The write's provenance stays `admin_manual` with
  // the admin as decider (D20): a prefilled field the admin confirmed IS the
  // admin's assertion; this records which words they did not choose.
  if (body.proposerContext) params.proposer_context = body.proposerContext;
  try {
    const data = await client.dispatchWrite(TOOL, "add_lexicon_entry", params);
    return json({ entry: mapLexiconEntry(data) }, { status: 201 });
  } catch (err) {
    return hermesErrorToProblem(err);
  }
}

// FR-24: free text -> a drafted structured entry the S02 form pre-fills with.
//
// It is a POST and not a GET because it spends a billed model completion; and it
// is `dispatch`-shaped through the AGENT client rather than a governed write
// because it writes nothing at all. The admin's confirm is the governed action,
// and it is unchanged (NFR-3).
//
// A failed derivation is NOT an error here. `drafted: false` rides a 200 with a
// reason, so the console renders "the copilot could not read that" beside a form
// the admin can still type into -- a 502 would blank the console over a model
// having nothing to say.
export async function handleDraftLexiconViaApi(
  agent: HermesAgentClient,
  text: string,
): Promise<Response> {
  if (typeof text !== "string" || text.trim().length === 0) {
    return problem(400, "text is required");
  }
  try {
    return json({ draft: await agent.draftLexiconEntry(text) });
  } catch (err) {
    return hermesErrorToProblem(err);
  }
}
