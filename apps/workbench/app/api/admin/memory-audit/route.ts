import { handleGetMemoryAuditViaApi } from "@/lib/bff/admin/memory-audit";
import { json, problem } from "@/lib/bff/respond";
import { withSession } from "@/lib/bff/with-session";
import { HermesApiClient } from "@/lib/gateway/hermes-api-client";
import { resolveProfileApiConfig } from "@/lib/gateway/hermes-api-config";

export const runtime = "nodejs";

// FR-20 supervisor memory audit view (0.0.3 S20). /api/admin/* is already
// admin-gated by withSession (ADR-0093, lib/auth/access.ts's isAdminPath). See
// lib/bff/admin/memory-audit.ts's header comment for why this admin route
// dispatches over the Internal Copilot Profile API rather than the Supervisor
// Admin Profile API createAdminApiClient (deps.ts) uses elsewhere in this group.
export const GET = withSession((req, { session }) => {
  const caseId = new URL(req.url).searchParams.get("case_id") ?? "";
  if (!caseId) return problem(400, "case_id is required");
  const apiConfig = resolveProfileApiConfig(
    process.env.HERMES_COPILOT_API_URL,
    process.env.HERMES_COPILOT_API_TOKEN,
  );
  // API-path-only (mirrors the copilot preferences GET): no in-memory-store
  // concept for Customer Memory, so an unconfigured backend degrades to an
  // empty view rather than a silent store no-op.
  if (!apiConfig) return json({ slots: [], history: [] });
  const client = new HermesApiClient({ ...apiConfig, actorAccountId: session.accountId });
  return handleGetMemoryAuditViaApi(client, caseId);
});
