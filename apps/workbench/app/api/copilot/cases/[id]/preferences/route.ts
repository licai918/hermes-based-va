import { createCopilotApiClient } from "@/lib/bff/copilot/deps";
import {
  handleGetPreferencesViaApi,
  handleUpsertPreferenceViaApi,
} from "@/lib/bff/copilot/preferences";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

// Customer Memory (PAC-4/S17): the read fails open (dispatch), the correction is a
// governed dispatchWrite carrying the acting rep.
export const GET = withSession((_req, { session, params }) =>
  handleGetPreferencesViaApi(createCopilotApiClient(session), params?.id ?? ""),
);

export const POST = withSession((req, { session, params }) =>
  handleUpsertPreferenceViaApi(req, createCopilotApiClient(session), params?.id ?? ""),
);
