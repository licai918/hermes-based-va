import { handleTriggerRetentionSweepViaApi } from "@/lib/bff/admin/retention";
import { createCopilotApiClient } from "@/lib/bff/copilot/deps";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

// FR-30 (0.0.3 S28): the governed retention-sweep trigger -- ages out
// customer_memory_slot rows per the ADR-0004/0116 class windows. The actor rides
// the client's actorAccountId into a governed dispatchWrite -- never a
// client-supplied param.
export const POST = withSession((_req, { session }) =>
  handleTriggerRetentionSweepViaApi(createCopilotApiClient(session)),
);
