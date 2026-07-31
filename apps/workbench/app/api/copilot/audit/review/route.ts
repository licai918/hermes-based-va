import { handleSubmitInteractionReviewViaApi } from "@/lib/bff/copilot/review";
import { createCopilotApiClient } from "@/lib/bff/copilot/deps";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

// 0.0.4 S04: supervisor/admin only, enforced by withSession's route-prefix gate
// over /api/copilot/audit/* (ADR-0093, lib/auth/access.ts) -- proven in
// lib/auth/access.test.ts. The acting employee rides along via
// createCopilotApiClient(session) so submit_interaction_review's audit row
// attributes to the real reviewer.
export const POST = withSession((req, { session }) =>
  handleSubmitInteractionReviewViaApi(req, createCopilotApiClient(session)),
);
