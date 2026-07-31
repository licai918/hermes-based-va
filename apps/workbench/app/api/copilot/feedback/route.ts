import { handleSubmitDraftFeedbackViaApi } from "@/lib/bff/copilot/feedback";
import { createCopilotApiClient } from "@/lib/bff/copilot/deps";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

// 0.0.4 S07: open to any authenticated workbench user -- the route sits under
// /api/copilot/ but not /api/copilot/audit/, so withSession's route-prefix gate
// (lib/auth/access.ts) leaves it unrestricted, which is correct since reps are
// the intended authors of draft feedback (see lib/bff/copilot/feedback.ts's
// module docstring). The acting rep rides along via
// createCopilotApiClient(session) so submit_draft_rating's audit row
// attributes to the real rep, and the Python handler's case-ownership gate
// (S06) refuses feedback on a case the rep doesn't hold.
export const POST = withSession((req, { session }) =>
  handleSubmitDraftFeedbackViaApi(req, createCopilotApiClient(session)),
);
