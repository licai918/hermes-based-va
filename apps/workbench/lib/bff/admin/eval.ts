// Eval-review handlers for the Admin BFF (ADR-0088 run review; ADR-0040 Knowledge
// Publish Eval Gate — failed_high blocks go-live/promotion, medium failures need
// sign-off). Pure and dependency-injected; the thin app/api/admin/eval route files
// wrap these with withSession and inject the real EvalStore singleton.
import {
  HermesApiClient,
  HermesApiError,
} from "../../gateway/hermes-api-client";
import { hermesErrorToProblem } from "../../gateway/hermes-error";
import type {
  EvalRunReport,
  EvalRunSummary,
  EvalScenarioResult,
  EvalSummary,
  ScenarioSeverity,
} from "../../gateway/eval-store";
import { json, problem } from "../respond";
import type { AdminDeps } from "./deps";

export function handleListRuns(deps: AdminDeps): Response {
  return json({ runs: deps.evalStore.listRuns() });
}

export function handleGetRun(runId: string, deps: AdminDeps): Response {
  const run = deps.evalStore.getRun(runId);
  if (!run) return problem(404, "run not found");
  return json({ run });
}

export function handleSignOff(runId: string, deps: AdminDeps): Response {
  const result = deps.evalStore.signOffMedium(runId, deps.session.accountId);
  if (result.ok) return json({ run: result.report });
  if (result.reason === "not_found") return problem(404, "run not found");
  if (result.reason === "not_required") {
    return problem(409, "no medium sign-off required");
  }
  return problem(409, "high-severity failures block sign-off");
}

export function handlePromote(runId: string, deps: AdminDeps): Response {
  const result = deps.evalStore.promotePending(runId);
  if (result.ok) return json({ run: result.report });
  if (result.reason === "not_found") return problem(404, "run not found");
  if (result.reason === "not_promotable") {
    return problem(409, "run is not a promotable policy_publish run");
  }
  if (result.reason === "failed_high") {
    return problem(409, "high-severity failures block promotion");
  }
  return problem(409, "medium failures must be signed off first");
}

// --- Per-profile API cutover (ADR-0141/0146 Increment 7) ---------------------
// The Supervisor Admin eval routes dispatch toee_eval_review over the per-profile
// Hermes API when HERMES_ADMIN_API_URL/TOKEN are configured (else the in-memory
// EvalStore). The list/get reads use dispatch (fail-open); sign-off and promote
// use dispatchWrite (fail-closed on the acting supervisor baked into the client),
// so a write can never land a NULL-actor audit row — the datastore enforces the
// same rule. Per-class error mapping turns a governed not_found/conflict into
// 404/409, and the governed messages match the store path (status + body parity).

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
