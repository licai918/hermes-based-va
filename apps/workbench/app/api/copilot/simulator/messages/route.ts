import { handleSimulatorIngress } from "@/lib/bff/copilot/simulator";
import { problem } from "@/lib/bff/respond";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

// FR-9 / S02: posts the simulated customer SMS to the REAL gateway webhook
// (§7 seam 1 -- no bypass chat). SIMPLETEXTING_WEBHOOK_TOKEN is the same shared
// secret hermes-runtime verifies against; SIMULATOR_GATEWAY_URL defaults to the
// local dev gateway.
export const POST = withSession((req) => {
  const webhookSecret = process.env.SIMPLETEXTING_WEBHOOK_TOKEN;
  if (!webhookSecret) {
    return problem(503, "Simulator gateway is not configured", {
      errorClass: "configuration_missing",
    });
  }
  const gatewayUrl = process.env.SIMULATOR_GATEWAY_URL || "http://localhost:8080";
  return handleSimulatorIngress(req, { gatewayUrl, webhookSecret });
});
