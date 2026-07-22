import { createCopilotApiClient } from "@/lib/bff/copilot/deps";
import {
  handleGetSimulatorEmailThread,
  handleGetSimulatorThread,
} from "@/lib/bff/copilot/simulator";
import { problem } from "@/lib/bff/respond";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

// FR-9 / S02 (SMS) + S18/FR-11 (email): reads the simulated thread back from
// message_turn (the mirror + the real inbound turn) via the same Case Thread
// Context read the copilot case view uses (ADR-0143). SMS is keyed by fromPhone
// (get_thread_by_phone); email by fromAddress (get_thread_by_email, S18) -- the
// simulator never learns the case_id the gateway's async webhook creates.
export const GET = withSession((req, { session }) => {
  const params = new URL(req.url).searchParams;
  const fromPhone = params.get("fromPhone");
  const fromAddress = params.get("fromAddress");
  if (!fromPhone && !fromAddress) {
    return problem(400, "fromPhone or fromAddress is required");
  }
  const client = createCopilotApiClient(session);
  return fromAddress
    ? handleGetSimulatorEmailThread(client, fromAddress)
    : handleGetSimulatorThread(client, fromPhone as string);
});
