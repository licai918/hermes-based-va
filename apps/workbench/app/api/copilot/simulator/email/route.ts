import { handleSimulatorEmailIngress } from "@/lib/bff/copilot/simulator";
import { problem } from "@/lib/bff/respond";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

// S18/FR-11: posts the simulated customer email to the REAL runtime webhook
// (§7 seam 1 -- no bypass chat), the email sibling of ../messages/route.ts.
// Same SIMPLETEXTING_WEBHOOK_TOKEN guard and SIMULATOR_GATEWAY_URL default --
// hermes-runtime verifies the simulated-email webhook with the same shared
// secret as the SMS webhook (gateway_app.py).
export const POST = withSession((req) => {
  const webhookSecret = process.env.SIMPLETEXTING_WEBHOOK_TOKEN;
  if (!webhookSecret) {
    return problem(503, "Simulator gateway is not configured", {
      errorClass: "configuration_missing",
    });
  }
  const gatewayUrl = process.env.SIMULATOR_GATEWAY_URL || "http://localhost:8080";
  return handleSimulatorEmailIngress(req, { gatewayUrl, webhookSecret });
});
