import {
  handleGetPreferencesViaApi,
  handleUpsertPreferenceViaApi,
} from "@/lib/bff/copilot/preferences";
import { json, problem } from "@/lib/bff/respond";
import { withSession } from "@/lib/bff/with-session";
import { HermesApiClient } from "@/lib/gateway/hermes-api-client";
import { resolveProfileApiConfig } from "@/lib/gateway/hermes-api-config";

export const runtime = "nodejs";

// API-path-only (PAC-4/S17): Customer Memory has no in-memory-store concept, so
// unlike the other case routes there is no store fallback -- an unconfigured
// backend degrades to an empty read (GET) or a governed 503 (POST), never a
// silent no-op store.
export const GET = withSession((_req, { session, params }) => {
  const caseId = params?.id ?? "";
  const apiConfig = resolveProfileApiConfig(
    process.env.HERMES_COPILOT_API_URL,
    process.env.HERMES_COPILOT_API_TOKEN,
  );
  if (!apiConfig) return json({ preferences: {} });
  const client = new HermesApiClient({
    ...apiConfig,
    actorAccountId: session.accountId,
  });
  return handleGetPreferencesViaApi(client, caseId);
});

export const POST = withSession((req, { session, params }) => {
  const caseId = params?.id ?? "";
  const apiConfig = resolveProfileApiConfig(
    process.env.HERMES_COPILOT_API_URL,
    process.env.HERMES_COPILOT_API_TOKEN,
  );
  if (!apiConfig) {
    return problem(503, "Customer Memory backend is not configured", {
      errorClass: "configuration_missing",
    });
  }
  const client = new HermesApiClient({
    ...apiConfig,
    actorAccountId: session.accountId,
  });
  return handleUpsertPreferenceViaApi(req, client, caseId);
});
