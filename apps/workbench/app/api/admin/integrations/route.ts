import { handleGetIntegrationsStatusViaApi } from "@/lib/bff/admin/integrations";
import { createAdminApiClient } from "@/lib/bff/admin/deps";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

// FR-23 (0.0.4 S15): the integrations status page read. /api/admin/integrations is
// gated to ADMIN-ONLY by withSession (canAccess -> requiresAdmin, lib/auth/access.ts)
// -- deliberately narrower than the supervisor+admin dead-letter view, because
// integrations are a credential surface (gap-review P4). Dispatches over the
// Supervisor Admin Profile API, which is the profile toee_integrations is
// allowlisted on. The handler returns config-presence booleans + version pins only,
// never a secret, and never a fabricated "healthy".
export const GET = withSession((_req, { session }) =>
  handleGetIntegrationsStatusViaApi(createAdminApiClient(session)),
);
