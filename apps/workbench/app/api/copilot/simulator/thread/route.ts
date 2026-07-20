import { handleGetSimulatorThread } from "@/lib/bff/copilot/simulator";
import { json, problem } from "@/lib/bff/respond";
import { withSession } from "@/lib/bff/with-session";
import { HermesApiClient } from "@/lib/gateway/hermes-api-client";
import { resolveProfileApiConfig } from "@/lib/gateway/hermes-api-config";

export const runtime = "nodejs";

// FR-9 / S02: reads the simulated thread back from message_turn (S01's mirror
// + the real inbound turn) via the same Case Thread Context read the copilot
// case view uses (ADR-0143), keyed by the from-phone the simulator posted
// (get_thread_by_phone -- the simulator never learns the case_id the gateway's
// async webhook creates). API-path-only, like preferences.ts: an unconfigured
// backend degrades to an empty thread rather than a silent in-memory-store
// no-op (the simulated turns only ever land in the real datastore).
export const GET = withSession((req, { session }) => {
  const fromPhone = new URL(req.url).searchParams.get("fromPhone");
  if (!fromPhone) return problem(400, "fromPhone is required");

  const apiConfig = resolveProfileApiConfig(
    process.env.HERMES_COPILOT_API_URL,
    process.env.HERMES_COPILOT_API_TOKEN,
  );
  if (!apiConfig) return json({ messages: [] });

  const client = new HermesApiClient({ ...apiConfig, actorAccountId: session.accountId });
  return handleGetSimulatorThread(client, fromPhone);
});
