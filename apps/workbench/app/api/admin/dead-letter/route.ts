import { handleListDeadLettersViaApi } from "@/lib/bff/admin/dead-letter";
import { createAdminApiClient } from "@/lib/bff/admin/deps";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

// FR-13 (0.0.4 S05): the dead-letter operator view -- dead jobs plus the
// outbound_send states S03/S04 leave that no dead-letter row captures.
// /api/admin/* is already gated to supervisor+admin by withSession (ADR-0093,
// lib/auth/access.ts). Dispatches over the Supervisor Admin Profile API, which is
// the profile toee_job_queue is allowlisted on. The handler refuses to fake an
// empty view (it 502s rather than swallow a missing table): "No dead jobs." is the
// one sentence this panel must never say falsely.
export const GET = withSession((_req, { session }) =>
  handleListDeadLettersViaApi(createAdminApiClient(session)),
);
