// Customer Memory retention sweep admin panel (0.0.3 S28, FR-30) for the Admin
// BFF (ADR-0093 admin route group). Pure and dependency-injected like the
// sibling admin/*.ts modules; the thin app/api/admin/retention* routes wrap
// this with withSession + a per-profile client.
//
// Dispatches over the Internal Copilot Profile API (HERMES_COPILOT_API_URL/
// TOKEN), NOT the Supervisor Admin Profile API createAdminApiClient (deps.ts)
// uses elsewhere in this folder: toee_retention is allowlisted for
// internal_copilot only (hermes/toee_hermes/plugin/profiles.py), same
// precedent as admin/metrics.ts and admin/agent-experience.ts. Admin-gating
// (ADR-0093) still comes from the BFF route itself (/api/admin/* +
// withSession's role check), not from which Hermes profile answers the
// dispatch. Both actions are admin-only on the Hermes side too
// (_AGENT_EXCLUDED_ACTIONS) -- never reachable from a live agent's tool loop.
//
// get_retention_status is READ, fail-open (dispatch, not dispatchWrite): a
// supervisor can view the panel with no actor attribution needed, same
// convention as handleGetAggregateMetricsViaApi. trigger_retention_sweep is a
// governed WRITE (deletes customer_memory_slot rows) -- dispatchWrite,
// fail-closed on a missing actor, same posture as handleDecideExperienceViaApi.
import type { HermesApiClient } from "../../gateway/hermes-api-client";
import { HermesApiError } from "../../gateway/hermes-api-client";
import { hermesErrorToProblem } from "../../gateway/hermes-error";
import { json } from "../respond";

export interface RetentionWindowsDays {
  verified: number;
  provisional: number;
}

export interface RetentionCounts {
  verified: number;
  provisional: number;
}

export interface RetentionStatus {
  lastRunAt: string | null;
  counts: RetentionCounts;
  totalDeleted: number;
  windowsDays: RetentionWindowsDays;
}

export interface RetentionSweepResult extends RetentionStatus {
  runAt: string;
}

// Fallback for an unconfigured backend (mirrors admin/metrics.ts's
// EMPTY_AGGREGATE_METRICS) -- structurally correct "never run" shape, not a
// fabricated number.
export const NEVER_RUN_RETENTION_STATUS: RetentionStatus = {
  lastRunAt: null,
  counts: { verified: 0, provisional: 0 },
  totalDeleted: 0,
  windowsDays: { verified: 730, provisional: 90 },
};

function malformed(detail: string): never {
  throw new HermesApiError("unexpected_error", `malformed retention payload: ${detail}`);
}

function requireNumber(value: unknown, field: string): number {
  if (typeof value !== "number" || Number.isNaN(value)) malformed(field);
  return value as number;
}

function requireNullableString(value: unknown, field: string): string | null {
  if (value === null) return null;
  if (typeof value !== "string") malformed(field);
  return value as string;
}

function requireCounts(value: unknown, field: string): RetentionCounts {
  if (typeof value !== "object" || value === null) malformed(field);
  const r = value as Record<string, unknown>;
  return {
    verified: requireNumber(r.verified, `${field}.verified`),
    provisional: requireNumber(r.provisional, `${field}.provisional`),
  };
}

function requireWindowsDays(value: unknown, field: string): RetentionWindowsDays {
  if (typeof value !== "object" || value === null) malformed(field);
  const r = value as Record<string, unknown>;
  return {
    verified: requireNumber(r.verified, `${field}.verified`),
    provisional: requireNumber(r.provisional, `${field}.provisional`),
  };
}

export function mapRetentionStatus(raw: unknown): RetentionStatus {
  if (typeof raw !== "object" || raw === null) malformed("root");
  const r = raw as Record<string, unknown>;
  return {
    lastRunAt: requireNullableString(r.last_run_at, "last_run_at"),
    counts: requireCounts(r.counts, "counts"),
    totalDeleted: requireNumber(r.total_deleted, "total_deleted"),
    windowsDays: requireWindowsDays(r.windows_days, "windows_days"),
  };
}

export function mapRetentionSweepResult(raw: unknown): RetentionSweepResult {
  if (typeof raw !== "object" || raw === null) malformed("root");
  const r = raw as Record<string, unknown>;
  return {
    lastRunAt: requireNullableString(r.run_at, "run_at"),
    runAt: requireNullableString(r.run_at, "run_at") ?? malformed("run_at"),
    counts: requireCounts(r.counts, "counts"),
    totalDeleted: requireNumber(r.total_deleted, "total_deleted"),
    windowsDays: requireWindowsDays(r.windows_days, "windows_days"),
  };
}

export async function handleGetRetentionStatusViaApi(
  client: HermesApiClient,
): Promise<Response> {
  try {
    const data = await client.dispatch("toee_retention", "get_retention_status", {});
    return json(mapRetentionStatus(data));
  } catch (err) {
    return hermesErrorToProblem(err);
  }
}

export async function handleTriggerRetentionSweepViaApi(
  client: HermesApiClient,
): Promise<Response> {
  try {
    const data = await client.dispatchWrite("toee_retention", "trigger_retention_sweep", {});
    return json(mapRetentionSweepResult(data));
  } catch (err) {
    return hermesErrorToProblem(err);
  }
}
