// Eval-review handlers for the Admin BFF (ADR-0088 run review; ADR-0040 Knowledge
// Publish Eval Gate — failed_high blocks go-live/promotion, medium failures need
// sign-off). API-only (0.0.4 S09): the thin app/api/admin/eval route files wrap
// these with withSession and inject the Supervisor Admin Profile API client. The
// gate itself is enforced by toee_eval_review server-side; this layer maps the
// governed verdict onto HTTP.
import {
  HermesApiClient,
  HermesApiError,
} from "../../gateway/hermes-api-client";
import { hermesErrorToProblem } from "../../gateway/hermes-error";
import { json } from "../respond";

// The wire shapes of an eval run (ADR-0074 standard JSON eval report + the ADR-0088
// list-pane row). Declared here, next to the mappers that produce them, since
// 0.0.4 S09 deleted the in-memory EvalStore they used to live in.
export type ScenarioSeverity = "high" | "medium" | "none";

export interface EvalScenarioResult {
  scenario_id: string;
  passed: boolean;
  failed_assertions: string[];
  severity: ScenarioSeverity;
}

export interface EvalSummary {
  total: number;
  passed: number;
  failed_high: number;
  failed_medium: number;
}

export interface EvalRunReport {
  run_id: string;
  suite: string;
  model_slug: string;
  prompt_version: string;
  knowledge_version: string;
  timestamp: string;
  scenarios: EvalScenarioResult[];
  summary: EvalSummary;
  signoff_required: boolean;
  // Governance overlay (not part of the on-disk report; merged in server-side).
  signed_off?: boolean;
  promoted?: boolean;
}

// Compact row for the list pane (ADR-0088 left pane columns).
export interface EvalRunSummary {
  run_id: string;
  suite: string;
  timestamp: string;
  passed: boolean;
  failed_high: number;
  failed_medium: number;
  knowledge_version: string;
  prompt_version: string;
}

// --- Per-profile API (ADR-0141/0146 Increment 7) ------------------------------
// The list/get reads use dispatch (fail-open); sign-off and promote use
// dispatchWrite (fail-closed on the acting supervisor baked into the client), so a
// write can never land a NULL-actor audit row — the datastore enforces the same
// rule. Per-class error mapping turns a governed not_found/conflict into 404/409.

const SEVERITIES = new Set<ScenarioSeverity>(["high", "medium", "none"]);

function evalString(r: Record<string, unknown>, key: string): string {
  const value = r[key];
  if (typeof value !== "string" || value.length === 0) {
    throw new HermesApiError("unexpected_error", `malformed eval run: ${key}`);
  }
  return value;
}

function evalInt(value: unknown, label: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new HermesApiError("unexpected_error", `malformed eval summary: ${label}`);
  }
  return value;
}

function asObject(raw: unknown, label: string): Record<string, unknown> {
  if (typeof raw !== "object" || raw === null) {
    throw new HermesApiError("unexpected_error", `malformed ${label}`);
  }
  return raw as Record<string, unknown>;
}

function mapSummary(raw: unknown): EvalSummary {
  const r = asObject(raw, "eval summary");
  return {
    total: evalInt(r.total, "total"),
    passed: evalInt(r.passed, "passed"),
    failed_high: evalInt(r.failed_high, "failed_high"),
    failed_medium: evalInt(r.failed_medium, "failed_medium"),
  };
}

function mapScenario(raw: unknown): EvalScenarioResult {
  const r = asObject(raw, "eval scenario");
  if (!SEVERITIES.has(r.severity as ScenarioSeverity)) {
    throw new HermesApiError(
      "unexpected_error",
      `unknown scenario severity: ${String(r.severity)}`,
    );
  }
  const failed = Array.isArray(r.failed_assertions) ? r.failed_assertions : [];
  return {
    scenario_id: evalString(r, "scenario_id"),
    passed: r.passed === true,
    failed_assertions: failed.map((a) => String(a)),
    severity: r.severity as ScenarioSeverity,
  };
}

// Validates a dispatched eval-run report (ADR-0070 runtime guard) onto the wire
// EvalRunReport, rejecting a contract violation as a governed HermesApiError so a
// bad upstream surfaces on the ADR-0090 banner (mirrors mapPolicySlot).
export function mapEvalRunReport(raw: unknown): EvalRunReport {
  const r = asObject(raw, "eval run report");
  const scenarios = Array.isArray(r.scenarios) ? r.scenarios : [];
  return {
    run_id: evalString(r, "run_id"),
    suite: evalString(r, "suite"),
    model_slug: evalString(r, "model_slug"),
    prompt_version: evalString(r, "prompt_version"),
    knowledge_version: evalString(r, "knowledge_version"),
    timestamp: evalString(r, "timestamp"),
    scenarios: scenarios.map(mapScenario),
    summary: mapSummary(r.summary),
    signoff_required: r.signoff_required === true,
    signed_off: r.signed_off === true,
    promoted: r.promoted === true,
  };
}

// Validates a dispatched compact summary row onto the wire EvalRunSummary.
export function mapEvalRunSummary(raw: unknown): EvalRunSummary {
  const r = asObject(raw, "eval run summary");
  return {
    run_id: evalString(r, "run_id"),
    suite: evalString(r, "suite"),
    timestamp: evalString(r, "timestamp"),
    passed: r.passed === true,
    failed_high: evalInt(r.failed_high, "failed_high"),
    failed_medium: evalInt(r.failed_medium, "failed_medium"),
    knowledge_version: evalString(r, "knowledge_version"),
    prompt_version: evalString(r, "prompt_version"),
  };
}

export async function handleListRunsViaApi(
  client: HermesApiClient,
): Promise<Response> {
  try {
    const data = (await client.dispatch("toee_eval_review", "list_eval_runs")) as {
      runs?: unknown;
    };
    const rows = Array.isArray(data?.runs) ? data.runs : [];
    return json({ runs: rows.map(mapEvalRunSummary) });
  } catch (err) {
    return hermesErrorToProblem(err);
  }
}

export async function handleGetRunViaApi(
  runId: string,
  client: HermesApiClient,
): Promise<Response> {
  try {
    const data = (await client.dispatch("toee_eval_review", "get_eval_run", {
      run_id: runId,
    })) as { run?: unknown };
    return json({ run: mapEvalRunReport(data.run) });
  } catch (err) {
    return hermesErrorToProblem(err);
  }
}

export async function handleSignOffViaApi(
  runId: string,
  client: HermesApiClient,
): Promise<Response> {
  try {
    const data = (await client.dispatchWrite(
      "toee_eval_review",
      "sign_off_medium_failure",
      { run_id: runId },
    )) as { run?: unknown };
    return json({ run: mapEvalRunReport(data.run) });
  } catch (err) {
    return hermesErrorToProblem(err);
  }
}

export async function handlePromoteViaApi(
  runId: string,
  client: HermesApiClient,
): Promise<Response> {
  try {
    const data = (await client.dispatchWrite(
      "toee_eval_review",
      "promote_pending_policy",
      { run_id: runId },
    )) as { run?: unknown };
    return json({ run: mapEvalRunReport(data.run) });
  } catch (err) {
    return hermesErrorToProblem(err);
  }
}
