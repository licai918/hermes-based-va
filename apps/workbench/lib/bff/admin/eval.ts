// Eval-review handlers for the Admin BFF (ADR-0088 run review; ADR-0040 Knowledge
// Publish Eval Gate — failed_high blocks go-live/promotion, medium failures need
// sign-off). Pure and dependency-injected; the thin app/api/admin/eval route files
// wrap these with withSession and inject the real EvalStore singleton.
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
