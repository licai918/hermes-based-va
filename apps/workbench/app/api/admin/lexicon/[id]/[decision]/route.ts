import {
  LEXICON_DECISION_ACTIONS,
  handleDecideLexiconViaApi,
  type LexiconDecision,
} from "@/lib/bff/admin/semantic-lexicon";
import { createCopilotApiClient } from "@/lib/bff/copilot/deps";
import { problem } from "@/lib/bff/respond";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

// FR-3 (0.0.5 S02): the human gate -- Approve / Reject / Retire. One dynamic
// segment rather than three near-identical route files; the decision is checked
// against the allowlist here, so an unknown segment is a 404 and never reaches
// dispatch. The actor rides the client's actorAccountId (from the signed-in
// session) into a governed dispatchWrite -- never a client-supplied param.
export const POST = withSession((_req, { session, params }) => {
  const id = params?.id ?? "";
  if (!id) return problem(400, "id is required");
  const decision = params?.decision ?? "";
  // `hasOwn`, not `in`: `in` walks the prototype chain, so `toString`,
  // `constructor` and `__proto__` all passed this guard and dispatched a
  // `Function` as an action name -- a confusing 500 where a 404 was the whole
  // point of checking.
  if (!Object.hasOwn(LEXICON_DECISION_ACTIONS, decision)) {
    return problem(404, `unknown lexicon decision "${decision}"`);
  }
  return handleDecideLexiconViaApi(
    createCopilotApiClient(session),
    decision as LexiconDecision,
    id,
  );
});
