import { createCopilotApiClient } from "@/lib/bff/copilot/deps";
import { handleSimulatorLinkIdentity } from "@/lib/bff/copilot/simulator";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

// 0.0.3 S05 (FR-13): the simulator's "link identity" control -- a governed Identity
// Graph write over tools:dispatch. The Hermes dispatch server itself denies this
// action unless booted with REPLY_SENDER=simulated (NFR-4); an
// unexpected-in-production call comes back as a governed 403 through
// hermesErrorToProblem, never a silent success.
export const POST = withSession((req, { session }) =>
  handleSimulatorLinkIdentity(req, createCopilotApiClient(session)),
);
