// Aggregate-metrics admin panel read handler (0.0.3 S26, FR-28) for the Admin
// BFF (ADR-0093 admin route group). Pure and dependency-injected like the
// sibling admin/*.ts modules; the thin app/api/admin/metrics route wraps this
// with withSession + a per-profile client.
//
// Dispatches over the Internal Copilot Profile API (HERMES_COPILOT_API_URL/
// TOKEN), NOT the Supervisor Admin Profile API createAdminApiClient (deps.ts)
// uses elsewhere in this folder: toee_metrics is allowlisted for
// internal_copilot only (hermes/toee_hermes/plugin/profiles.py), same
// precedent as admin/memory-audit.ts and admin/agent-experience.ts.
// Admin-gating (ADR-0093) still comes from the BFF route itself (/api/admin/*
// + withSession's role check), not from which Hermes profile answers the
// dispatch. get_aggregate_metrics is admin-only on the Hermes side too
// (_AGENT_EXCLUDED_ACTIONS) -- never reachable from a live agent's tool loop.
//
// READ, fail-open (dispatch, not dispatchWrite): a supervisor can view the
// panel with no actor attribution needed, same convention as
// handleListAgentExperienceViaApi.
import type { HermesApiClient } from "../../gateway/hermes-api-client";
import { HermesApiError } from "../../gateway/hermes-api-client";
import { hermesErrorToProblem } from "../../gateway/hermes-error";
import { json } from "../respond";

export interface SlotsPopulatedDistribution {
  "1": number;
  "2": number;
  "3": number;
  "4": number;
}

// Advisory, judge-sampled (S22/S27, C7 core question) -- NEVER gating. The
// scheduled honored_rate job (FR-31) persists an aggregate; `live: true` carries
// the rate plus provenance (sample size, eligible population, window, `asOf`).
// `live: false` is the honest "not yet computed" state -- never a silent zero,
// never a fabricated rate; the provenance fields are null then.
export interface HonoredRate {
  live: boolean;
  rate: number | null;
  sampleSize: number | null;
  candidateTotal: number | null;
  undetermined: number | null;
  windowSeconds: number | null;
  asOf: string | null;
  label: string;
}

export interface ProposalOutcomes {
  accepted: number;
  dismissed: number;
  rate: number | null;
}

// Per-layer read latency (0.0.5 S18, FR-26). One tile per memory-read site plus
// the total-vs-SLO tile; percentiles come from `metric_event.duration_ms`
// (migration 0023) via hermes_runtime.latency.
//
// `budgetMs` is null for most tiles ON PURPOSE: S18 measures and displays, S19
// owns enforcement, so only two lines exist today -- the owner's 150ms p95 on
// the total, and L5's own shipped retrieval deadline. `breached` is null (never
// false) wherever there is no budget or no sample: a false would render an
// unmeasured tile as a green "within budget".
export interface LatencyTile {
  metric: string;
  layer: string;
  label: string;
  p50Ms: number | null;
  p95Ms: number | null;
  samples: number;
  budgetMs: number | null;
  inSloTotal: boolean;
  breached: boolean | null;
}

export interface LatencyMetrics {
  sloP95Ms: number;
  notMeasuredLabel: string;
  total: LatencyTile;
  layers: LatencyTile[];
}

export interface AggregateMetrics {
  memoryInjection: { injected: number; total: number; rate: number | null };
  knowledgeSearch: { found: number; total: number; rate: number | null };
  slotsPopulatedDistribution: SlotsPopulatedDistribution;
  honoredRate: HonoredRate;
  mergeCount: number;
  correctionCount: number;
  proposalOutcomes: ProposalOutcomes;
  // S21/FR-30: real once-per-action counters, no longer proxied -- plain totals
  // like mergeCount/correctionCount.
  selfServiceUsage: number;
  l6ConfirmedEntries: number;
  // S18/FR-26: per-layer read latency + the SLO tile.
  latency: LatencyMetrics;
}

function malformed(detail: string): never {
  throw new HermesApiError("unexpected_error", `malformed aggregate metrics payload: ${detail}`);
}

function requireNumber(value: unknown, field: string): number {
  if (typeof value !== "number" || Number.isNaN(value)) malformed(field);
  return value as number;
}

function optionalNumber(value: unknown, field: string): number | null {
  if (value === null) return null;
  return requireNumber(value, field);
}

// Provenance fields are genuinely absent before the first honored_rate run, so a
// missing (undefined) value reads as null, same as an explicit null -- unlike the
// strict optionalNumber above, which malforms on undefined.
function nullableNumber(value: unknown, field: string): number | null {
  if (value === null || value === undefined) return null;
  return requireNumber(value, field);
}

function nullableString(value: unknown, field: string): string | null {
  if (value === null || value === undefined) return null;
  return requireString(value, field);
}

function requireBoolean(value: unknown, field: string): boolean {
  if (typeof value !== "boolean") malformed(field);
  return value as boolean;
}

function requireString(value: unknown, field: string): string {
  if (typeof value !== "string") malformed(field);
  return value as string;
}

function requireObject(value: unknown, field: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null) malformed(field);
  return value as Record<string, unknown>;
}

function nullableBoolean(value: unknown, field: string): boolean | null {
  if (value === null || value === undefined) return null;
  return requireBoolean(value, field);
}

function mapLatencyTile(raw: unknown, field: string): LatencyTile {
  const t = requireObject(raw, field);
  return {
    metric: requireString(t.metric, `${field}.metric`),
    layer: requireString(t.layer, `${field}.layer`),
    label: requireString(t.label, `${field}.label`),
    p50Ms: nullableNumber(t.p50_ms, `${field}.p50_ms`),
    p95Ms: nullableNumber(t.p95_ms, `${field}.p95_ms`),
    samples: requireNumber(t.samples, `${field}.samples`),
    budgetMs: nullableNumber(t.budget_ms, `${field}.budget_ms`),
    inSloTotal: requireBoolean(t.in_slo_total, `${field}.in_slo_total`),
    breached: nullableBoolean(t.breached, `${field}.breached`),
  };
}

function mapLatency(raw: unknown): LatencyMetrics {
  const l = requireObject(raw, "latency");
  if (!Array.isArray(l.layers)) malformed("latency.layers");
  return {
    sloP95Ms: requireNumber(l.slo_p95_ms, "latency.slo_p95_ms"),
    notMeasuredLabel: requireString(l.not_measured_label, "latency.not_measured_label"),
    total: mapLatencyTile(l.total, "latency.total"),
    layers: (l.layers as unknown[]).map((tile, i) => mapLatencyTile(tile, `latency.layers[${i}]`)),
  };
}

export function mapAggregateMetrics(raw: unknown): AggregateMetrics {
  const r = requireObject(raw, "root");

  const mem = requireObject(r.memory_injection, "memory_injection");
  const know = requireObject(r.knowledge_search, "knowledge_search");
  const dist = requireObject(r.slots_populated_distribution, "slots_populated_distribution");
  const honored = requireObject(r.honored_rate, "honored_rate");
  const outcomes = requireObject(r.proposal_outcomes, "proposal_outcomes");

  return {
    memoryInjection: {
      injected: requireNumber(mem.injected, "memory_injection.injected"),
      total: requireNumber(mem.total, "memory_injection.total"),
      rate: optionalNumber(mem.rate, "memory_injection.rate"),
    },
    knowledgeSearch: {
      found: requireNumber(know.found, "knowledge_search.found"),
      total: requireNumber(know.total, "knowledge_search.total"),
      rate: optionalNumber(know.rate, "knowledge_search.rate"),
    },
    slotsPopulatedDistribution: {
      "1": requireNumber(dist["1"], "slots_populated_distribution.1"),
      "2": requireNumber(dist["2"], "slots_populated_distribution.2"),
      "3": requireNumber(dist["3"], "slots_populated_distribution.3"),
      "4": requireNumber(dist["4"], "slots_populated_distribution.4"),
    },
    honoredRate: {
      live: requireBoolean(honored.live, "honored_rate.live"),
      rate: optionalNumber(honored.rate, "honored_rate.rate"),
      sampleSize: nullableNumber(honored.sample_size, "honored_rate.sample_size"),
      candidateTotal: nullableNumber(honored.candidate_total, "honored_rate.candidate_total"),
      undetermined: nullableNumber(honored.undetermined_count, "honored_rate.undetermined_count"),
      windowSeconds: nullableNumber(honored.window_seconds, "honored_rate.window_seconds"),
      asOf: nullableString(honored.as_of, "honored_rate.as_of"),
      label: requireString(honored.label, "honored_rate.label"),
    },
    mergeCount: requireNumber(r.merge_count, "merge_count"),
    correctionCount: requireNumber(r.correction_count, "correction_count"),
    proposalOutcomes: {
      accepted: requireNumber(outcomes.accepted, "proposal_outcomes.accepted"),
      dismissed: requireNumber(outcomes.dismissed, "proposal_outcomes.dismissed"),
      rate: optionalNumber(outcomes.rate, "proposal_outcomes.rate"),
    },
    selfServiceUsage: requireNumber(r.self_service_usage, "self_service_usage"),
    l6ConfirmedEntries: requireNumber(r.l6_confirmed_entries, "l6_confirmed_entries"),
    // Required, not optional: both twins ship the block (the mock's zero-sample
    // copy is pinned equal to the Postgres one). A tolerant mapper would let a
    // twin silently drop it and render "not yet measured" forever.
    latency: mapLatency(r.latency),
  };
}

export async function handleGetAggregateMetricsViaApi(
  client: HermesApiClient,
): Promise<Response> {
  try {
    const data = await client.dispatch("toee_metrics", "get_aggregate_metrics", {});
    return json(mapAggregateMetrics(data));
  } catch (err) {
    return hermesErrorToProblem(err);
  }
}
