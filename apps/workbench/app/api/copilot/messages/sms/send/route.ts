import { createCopilotApiClient } from "@/lib/bff/copilot/deps";
import { handleSmsSendViaApi } from "@/lib/bff/copilot/messages";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

// ADR-0141 / #42: the governed SMS send runs over tools:dispatch, so the vendor
// capture, the thread mirror and the sms_send audit land server-side in one
// transaction.
export const POST = withSession((req, { session }) =>
  handleSmsSendViaApi(req, createCopilotApiClient(session), session),
);
