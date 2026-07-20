import { handleSimulatorLinkIdentity } from "@/lib/bff/copilot/simulator";
import { problem } from "@/lib/bff/respond";
import { withSession } from "@/lib/bff/with-session";
import { HermesApiClient } from "@/lib/gateway/hermes-api-client";
import { resolveProfileApiConfig } from "@/lib/gateway/hermes-api-config";

export const runtime = "nodejs";

// 0.0.3 S05 (FR-13): the simulator's "link identity" control. API-path-only
// like preferences.ts -- link_identity is a governed Identity Graph write with
// no in-memory-store concept, so an unconfigured backend degrades to a
// governed 503 rather than a silent no-op store. The Hermes dispatch server
// itself denies this action unless booted with REPLY_SENDER=simulated
// (NFR-4); an unexpected-in-production call still comes back as a governed
// 403 through hermesErrorToProblem, never a silent success.
export const POST = withSession((req, { session }) => {
  const apiConfig = resolveProfileApiConfig(
    process.env.HERMES_COPILOT_API_URL,
    process.env.HERMES_COPILOT_API_TOKEN,
  );
  if (!apiConfig) {
    return problem(503, "Identity Graph backend is not configured", {
      errorClass: "configuration_missing",
    });
  }
  const client = new HermesApiClient({
    ...apiConfig,
    actorAccountId: session.accountId,
  });
  return handleSimulatorLinkIdentity(req, client);
});
