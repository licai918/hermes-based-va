import {
  handleGetSimulatorEmailThread,
  handleGetSimulatorThread,
} from "@/lib/bff/copilot/simulator";
import { json, problem } from "@/lib/bff/respond";
import { withSession } from "@/lib/bff/with-session";
import { HermesApiClient } from "@/lib/gateway/hermes-api-client";
import { resolveProfileApiConfig } from "@/lib/gateway/hermes-api-config";

export const runtime = "nodejs";

// FR-9 / S02 (SMS) + S18/FR-11 (email): reads the simulated thread back from
// message_turn (the mirror + the real inbound turn) via the same Case Thread
// Context read the copilot case view uses (ADR-0143). SMS is keyed by
// fromPhone (get_thread_by_phone); email is keyed by fromAddress
// (get_thread_by_email, S18) -- the simulator never learns the case_id the
// gateway's async webhook creates either way. API-path-only, like
// preferences.ts: an unconfigured backend degrades to an empty thread rather
// than a silent in-memory-store no-op (the simulated turns only ever land in
// the real datastore).
export const GET = withSession((req, { session }) => {
  const params = new URL(req.url).searchParams;
  const fromPhone = params.get("fromPhone");
  const fromAddress = params.get("fromAddress");
  if (!fromPhone && !fromAddress) {
    return problem(400, "fromPhone or fromAddress is required");
  }

  const apiConfig = resolveProfileApiConfig(
    process.env.HERMES_COPILOT_API_URL,
    process.env.HERMES_COPILOT_API_TOKEN,
  );
  if (!apiConfig) return json({ caseId: null, messages: [] });

  const client = new HermesApiClient({ ...apiConfig, actorAccountId: session.accountId });
  return fromAddress
    ? handleGetSimulatorEmailThread(client, fromAddress)
    : handleGetSimulatorThread(client, fromPhone as string);
});
