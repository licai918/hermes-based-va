import { EMPTY_DEAD_LETTER_VIEW, handleListDeadLettersViaApi } from "@/lib/bff/admin/dead-letter";
import { createAdminApiClient } from "@/lib/bff/admin/deps";
import { json } from "@/lib/bff/respond";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

// FR-13 (0.0.4 S05): the dead-letter operator view -- dead jobs plus the
// outbound_send states S03/S04 leave that no dead-letter row captures.
// /api/admin/* is already gated to supervisor+admin by withSession (ADR-0093,
// lib/auth/access.ts). Dispatches over the Supervisor Admin Profile API, which
// is the profile toee_job_queue is allowlisted on. Read-only; an unconfigured
// backend degrades to the honest empty view rather than an error banner.
export const GET = withSession((_req, { session }) => {
  const client = createAdminApiClient(session);
  if (!client) return json(EMPTY_DEAD_LETTER_VIEW);
  return handleListDeadLettersViaApi(client);
});
