// The unified review inbox (0.0.5 S15, FR-22 / US4 / US9) for the Admin BFF
// (ADR-0093 admin route group). Pure and dependency-injected like the sibling
// admin/*.ts modules; the thin app/api/admin/inbox routes wrap these with
// withSession + a per-profile client.
//
// FR-22 asks for ONE queue holding every pending memory decision. That queue has
// three sources, and the MERGE lives here rather than in Hermes on purpose: two
// of the three are existing governed reads that already work
// (list_agent_experience, list_lexicon_entries), so a server-side merge would be
// a fourth read re-deriving what those two already return, and a second place
// for the pending rule to drift. Merging in the BFF also keeps the Re-classify
// and decide paths honest -- each decision dispatches to the layer's OWN
// governed action, and the table below is the whole routing contract.
//
// Dispatches over the Internal Copilot Profile API (HERMES_COPILOT_API_URL/
// TOKEN), NOT the Supervisor Admin one: all three tools are allowlisted for
// internal_copilot only (hermes/toee_hermes/plugin/profiles.py). Admin-gating
// still comes from the route (/api/admin/* + withSession's role check).
//
// READS use `dispatch`; every WRITE uses `dispatchWrite`, which refuses before
// the network call when no acting account is configured -- defense in depth in
// front of Hermes's own fail-closed policy_blocked (ADR-0148).
import type { HermesApiClient } from "../../gateway/hermes-api-client";
import { hermesErrorToProblem } from "../../gateway/hermes-error";
import { json, problem } from "../respond";
import { mapAgentExperienceEntry } from "./agent-experience";
import { mapLexiconEntry } from "./semantic-lexicon";

// D9 (BINDING): six kinds. The first two are rendered from their own tables; the
// rest are rows of the `review_item` store this slice ships.
export const INBOX_ITEM_KINDS = [
  "l6_proposal",
  "l7_proposal",
  "graduation",
  "blast_radius",
  "persona_review",
  "retirement_candidate",
] as const;
export type InboxItemKind = (typeof INBOX_ITEM_KINDS)[number];

export type InboxDecision = "accept" | "reject" | "acknowledge" | "dismiss";

type DispatchTarget = {
  tool: string;
  action: string;
  // Present only where the action takes the terminal status as a param, i.e.
  // the review_item store's single decide action.
  decision?: "acknowledged" | "dismissed";
};

const REVIEW_ITEM_DECISIONS: Record<"acknowledge" | "dismiss", DispatchTarget> = {
  acknowledge: {
    tool: "toee_review_inbox",
    action: "decide_review_item",
    decision: "acknowledged",
  },
  dismiss: {
    tool: "toee_review_inbox",
    action: "decide_review_item",
    decision: "dismissed",
  },
};

// The routing contract, and the reason this slice adds no decision primitive for
// a proposal: an Accept on an L6 row IS confirm_experience, an Accept on an L7
// row IS confirm_lexicon_entry. The inbox is a different door onto the same
// governed actions, never a second way to decide the same thing.
//
// The four review_item kinds share one entry by construction, so a kind added by
// S10/S20/S25 cannot land with no decisions and render as a row with no buttons.
export const INBOX_DECISION_DISPATCH: Record<
  InboxItemKind,
  Partial<Record<InboxDecision, DispatchTarget>>
> = {
  l6_proposal: {
    accept: { tool: "toee_agent_experience", action: "confirm_experience" },
    reject: { tool: "toee_agent_experience", action: "reject_experience" },
  },
  l7_proposal: {
    accept: { tool: "toee_semantic_lexicon", action: "confirm_lexicon_entry" },
    reject: { tool: "toee_semantic_lexicon", action: "reject_lexicon_entry" },
  },
  graduation: REVIEW_ITEM_DECISIONS,
  blast_radius: REVIEW_ITEM_DECISIONS,
  persona_review: REVIEW_ITEM_DECISIONS,
  retirement_candidate: REVIEW_ITEM_DECISIONS,
};

// The layer badge, claimed ONLY where the kind determines it. The four
// review_item kinds span layers whose emitting slices (S10/S20/S25) have not
// landed: blast_radius is about whichever layer's entry was retired, graduation
// is a promotion BETWEEN layers. A guessed badge would be a confident lie on the
// governance surface, so those render their kind and no layer. When an emitter
// lands and knows its layer, it can put it in `evidence` and this map can grow.
const LAYER_BY_KIND: Record<InboxItemKind, string | null> = {
  l6_proposal: "L6",
  l7_proposal: "L7",
  graduation: null,
  blast_radius: null,
  persona_review: null,
  retirement_candidate: null,
};

// D8's shared column: two reserved top-level keys, `heuristic` (S13's write-time
// advisory) and `copilot` (S16's triage annotation). Read optionally on every
// source, so this renders whatever has landed and nothing when neither has --
// S13 ships the proposal-row column in migration 0025 and S16 writes later.
export type InboxAnnotations = Record<string, unknown> | null;

export type InboxItem = {
  kind: InboxItemKind;
  layer: string | null;
  id: string;
  subject: string;
  detail: string | null;
  createdAt: number;
  annotations: InboxAnnotations;
  decisions: InboxDecision[];
  reclassifiable: boolean;
};

function annotationsOf(raw: unknown): InboxAnnotations {
  if (typeof raw !== "object" || raw === null) return null;
  const value = (raw as Record<string, unknown>).annotations;
  if (typeof value !== "object" || value === null) return null;
  const annotations = value as Record<string, unknown>;
  return Object.keys(annotations).length > 0 ? annotations : null;
}

function decisionsFor(kind: InboxItemKind): InboxDecision[] {
  return Object.keys(INBOX_DECISION_DISPATCH[kind]) as InboxDecision[];
}

function item(
  kind: InboxItemKind,
  fields: {
    id: string;
    subject: string;
    detail: string | null;
    createdAt: number;
    annotations: InboxAnnotations;
  },
): InboxItem {
  return {
    kind,
    layer: LAYER_BY_KIND[kind],
    ...fields,
    decisions: decisionsFor(kind),
    // Re-classify moves a mis-filed PROPOSAL to the other layer's queue. Only
    // l6_proposal has a route today -- see read_reclassification in
    // toee_hermes/drivers/mock/review_item.py for why the reverse is refused
    // rather than half-built.
    reclassifiable: kind === "l6_proposal",
  };
}

function reviewItemToInboxItem(raw: unknown): InboxItem | null {
  if (typeof raw !== "object" || raw === null) return null;
  const r = raw as Record<string, unknown>;
  const kind = r.kind;
  if (!(INBOX_ITEM_KINDS as readonly unknown[]).includes(kind)) return null;
  const createdAt = typeof r.created_at === "string" ? Date.parse(r.created_at) : NaN;
  return item(kind as InboxItemKind, {
    id: String(r.id ?? ""),
    subject: String(r.subject_ref ?? ""),
    detail:
      r.evidence && typeof r.evidence === "object"
        ? JSON.stringify(r.evidence)
        : null,
    createdAt: Number.isNaN(createdAt) ? 0 : createdAt,
    annotations: annotationsOf(raw),
  });
}

function entriesOf(data: unknown, key: "entries" | "items"): unknown[] {
  if (typeof data !== "object" || data === null) return [];
  const value = (data as Record<string, unknown>)[key];
  return Array.isArray(value) ? value : [];
}

/**
 * FR-22's ONE queue: every pending memory decision, from all three sources.
 *
 * `count` is the inbox badge. It is the size of the merged queue, not any one
 * source's share -- an admin's "N waiting" has to mean what the page will show
 * them.
 */
export async function handleListInboxViaApi(
  client: HermesApiClient,
): Promise<Response> {
  try {
    const [l6, l7, stored] = await Promise.all([
      // list_agent_experience shipped unfiltered in 0.0.3 S22 and still has no
      // status param, so the pending-only rule is applied below rather than
      // server-side. The two filtered reads DO push their filter down.
      client.dispatch("toee_agent_experience", "list_agent_experience", {}),
      client.dispatch("toee_semantic_lexicon", "list_lexicon_entries", {
        status: "proposed",
      }),
      client.dispatch("toee_review_inbox", "list_review_items", {
        status: "open",
      }),
    ]);

    const items: InboxItem[] = [
      ...entriesOf(l6, "entries")
        .map((raw) => ({ raw, entry: mapAgentExperienceEntry(raw) }))
        .filter(({ entry }) => entry.status === "proposed")
        .map(({ raw, entry }) =>
          item("l6_proposal", {
            id: entry.id,
            subject: entry.content,
            detail: entry.kind,
            createdAt: entry.createdAt,
            annotations: annotationsOf(raw),
          }),
        ),
      ...entriesOf(l7, "entries")
        .map((raw) => ({ raw, entry: mapLexiconEntry(raw) }))
        .filter(({ entry }) => entry.status === "proposed")
        .map(({ raw, entry }) =>
          item("l7_proposal", {
            id: entry.id,
            subject: `${entry.surfaceForm} → ${entry.canonicalForm}`,
            detail: entry.evidence,
            createdAt: entry.createdAt,
            annotations: annotationsOf(raw),
          }),
        ),
      ...entriesOf(stored, "items")
        .map(reviewItemToInboxItem)
        .filter((i): i is InboxItem => i !== null),
    ].sort((a, b) => b.createdAt - a.createdAt);

    return json({ items, count: items.length });
  } catch (err) {
    return hermesErrorToProblem(err);
  }
}

/**
 * One inbox decision, routed to the layer that owns it (no new primitives).
 *
 * A decision the kind does not offer is a 400 HERE rather than a dispatch: the
 * BFF can already see it will not work, and Hermes would classify the miss as
 * `unexpected_error`, which the house error map turns into a 502 the admin reads
 * as "Bad Gateway" (the S02 precedent).
 */
export async function handleDecideInboxItemViaApi(
  client: HermesApiClient,
  kind: string,
  id: string,
  decision: string,
): Promise<Response> {
  const routes = INBOX_DECISION_DISPATCH[kind as InboxItemKind];
  const target = routes?.[decision as InboxDecision];
  if (!target) {
    return problem(400, `"${decision}" is not available for "${kind}" items`);
  }
  const params: Record<string, unknown> = { id };
  if (target.decision) params.decision = target.decision;
  try {
    const data = await client.dispatchWrite(target.tool, target.action, params);
    return json({ kind, id, result: data });
  } catch (err) {
    return hermesErrorToProblem(err);
  }
}

/**
 * FR-22's Re-classify: move a mis-filed proposal to the other layer's queue
 * instead of reject-and-retype.
 *
 * ONE governed action on the Hermes side does both halves in one transaction and
 * audits both; this only shapes the request and pays the same 400-not-502 debt
 * the add form does.
 */
export async function handleReclassifyInboxItemViaApi(
  client: HermesApiClient,
  body: {
    sourceKind?: string;
    id?: string;
    domain?: string;
    entryKind?: string;
    surfaceForm?: string;
    canonicalForm?: string;
  },
): Promise<Response> {
  const required = {
    sourceKind: body.sourceKind,
    id: body.id,
    domain: body.domain,
    entryKind: body.entryKind,
    surfaceForm: body.surfaceForm,
    canonicalForm: body.canonicalForm,
  };
  for (const [name, value] of Object.entries(required)) {
    if (typeof value !== "string" || value.trim().length === 0) {
      return problem(400, `${name} is required`);
    }
  }
  try {
    const data = await client.dispatchWrite(
      "toee_review_inbox",
      "reclassify_proposal",
      {
        source_kind: body.sourceKind,
        id: body.id,
        domain: body.domain,
        entry_kind: body.entryKind,
        surface_form: body.surfaceForm,
        canonical_form: body.canonicalForm,
      },
    );
    const d = (data ?? {}) as Record<string, unknown>;
    return json({
      source: d.source ?? null,
      target: d.target ?? null,
      reclassified: d.reclassified ?? null,
    });
  } catch (err) {
    return hermesErrorToProblem(err);
  }
}
