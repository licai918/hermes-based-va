import { createAdminApiClient } from "@/lib/bff/admin/deps";
import { handleGetCorpusStatusViaApi } from "@/lib/bff/admin/knowledge";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

export const GET = withSession((_req, { session }) =>
  handleGetCorpusStatusViaApi(createAdminApiClient(session)),
);
