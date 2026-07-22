import { handleListDeadLettersViaApi } from "@/lib/bff/admin/dead-letter";
import { createAdminApiClient } from "@/lib/bff/admin/deps";
import { problem } from "@/lib/bff/respond";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

// FR-13 (0.0.4 S05): the dead-letter operator view -- dead jobs plus the
// outbound_send states S03/S04 leave that no dead-letter row captures.
// /api/admin/* is already gated to supervisor+admin by withSession (ADR-0093,
// lib/auth/access.ts). Dispatches over the Supervisor Admin Profile API, which
// is the profile toee_job_queue is allowlisted on.
//
// An unconfigured backend is a 503, NOT an empty view (fix wave 1, finding 4).
// The house convention on read surfaces (admin/retention, admin/metrics) is to
// degrade to a structurally-correct empty shape, and it is wrong here: "No dead
// jobs." is the one sentence this panel must never say falsely. The handler
// itself already refuses to fake it (it 502s rather than swallow a missing
// table), and the sibling replay POST already 503s on the same condition.
export const GET = withSession((_req, { session }) => {
  const client = createAdminApiClient(session);
  if (!client) {
    return problem(503, "Dead-letter backend is not configured", {
      errorClass: "configuration_missing",
    });
  }
  return handleListDeadLettersViaApi(client);
});
