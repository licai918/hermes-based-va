import { describe, expect, it } from "vitest";
import { HermesApiClient } from "../../gateway/hermes-api-client";
import { handleSubmitDraftFeedbackViaApi } from "./feedback";

// 0.0.4 S07: submit_draft_rating's write is asserted at the HTTP-client seam --
// the dispatched { tool, action, params } envelope, actor attribution, and body
// validation -- mirroring review.test.ts's handleSubmitInteractionReviewViaApi
// coverage. Unlike that route, THIS one has no role boundary: it sits outside
// /api/copilot/audit/*, so any authenticated rep can reach it (proven at the
// canAccess layer in lib/auth/access.test.ts). These tests use a rep-shaped
// actor id to show the handler itself never turns a rep away.

type SentDispatch = {
  tool: string;
  action: string;
  params: Record<string, unknown>;
  actor_account_id?: string;
};

const REP_ACTOR = "seed-rep";

function jsonReq(body: unknown): Request {
  return new Request("http://localhost/api/copilot/feedback", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

function apiClient(
  fetchImpl: (url: string, init: RequestInit) => Promise<Response>,
  actorAccountId?: string,
): HermesApiClient {
  return new HermesApiClient({
    baseUrl: "http://copilot.internal",
    token: "tok",
    actorAccountId,
    fetchImpl,
  });
}

const RATING_ROW = {
  id: "drat_1",
  case_id: "c1",
  draft_correlation_id: "corr-1",
  draft_kind: "sms",
  draft_text: "Your tires are ready.",
  verdict: "down",
  reason_tags: ["wrong_tone"],
  comment: "too curt",
  rep_account_id: REP_ACTOR,
  created_at: "2026-06-01T12:00:00+00:00",
};

// Captures the dispatched envelope and returns RATING_ROW-shaped data.
function writeClient(
  data: unknown,
  capture?: (sent: SentDispatch) => void,
): HermesApiClient {
  return apiClient(async (_url, init) => {
    const sent = JSON.parse(init.body as string) as SentDispatch;
    capture?.(sent);
    return new Response(JSON.stringify({ ok: true, data }), { status: 200 });
  }, REP_ACTOR);
}

const BASE_BODY = {
  case_id: "c1",
  draft_correlation_id: "corr-1",
  draft_kind: "sms",
  draft_text: "Your tires are ready.",
};

describe("handleSubmitDraftFeedbackViaApi", () => {
  it("dispatches an up rating with no tags required, actor attached (rep session reaches it)", async () => {
    let sent: SentDispatch | null = null;
    const res = await handleSubmitDraftFeedbackViaApi(
      jsonReq({ ...BASE_BODY, verdict: "up" }),
      writeClient(
        { ...RATING_ROW, verdict: "up", reason_tags: [], comment: null },
        (s) => (sent = s),
      ),
    );

    expect(res.status).toBe(200);
    const body = (await res.json()) as { rating: { verdict: string } };
    expect(body.rating.verdict).toBe("up");

    const dispatched = sent as SentDispatch | null;
    expect(dispatched?.tool).toBe("toee_feedback");
    expect(dispatched?.action).toBe("submit_draft_rating");
    expect(dispatched?.params).toEqual({
      case_id: "c1",
      draft_correlation_id: "corr-1",
      draft_kind: "sms",
      draft_text: "Your tires are ready.",
      verdict: "up",
      reason_tags: [],
    });
    // Actor rides along automatically via the per-profile client (ADR-0141) --
    // and it is NOT a 403, proving a rep session can reach this route.
    expect(dispatched?.actor_account_id).toBe(REP_ACTOR);
  });

  it("dispatches a down rating with tags + comment", async () => {
    let sent: SentDispatch | null = null;
    const res = await handleSubmitDraftFeedbackViaApi(
      jsonReq({
        ...BASE_BODY,
        verdict: "down",
        reason_tags: ["wrong_tone"],
        comment: "too curt",
      }),
      writeClient(RATING_ROW, (s) => (sent = s)),
    );

    expect(res.status).toBe(200);
    const dispatched = sent as SentDispatch | null;
    expect(dispatched?.params).toEqual({
      case_id: "c1",
      draft_correlation_id: "corr-1",
      draft_kind: "sms",
      draft_text: "Your tires are ready.",
      verdict: "down",
      reason_tags: ["wrong_tone"],
      comment: "too curt",
    });
  });

  it("400s a down verdict with no reason tags (never dispatches)", async () => {
    let dispatched = false;
    const res = await handleSubmitDraftFeedbackViaApi(
      jsonReq({ ...BASE_BODY, verdict: "down" }),
      writeClient(RATING_ROW, () => (dispatched = true)),
    );
    expect(res.status).toBe(400);
    expect(dispatched).toBe(false);
  });

  it("400s an external-only reason tag (never dispatches)", async () => {
    let dispatched = false;
    const res = await handleSubmitDraftFeedbackViaApi(
      jsonReq({
        ...BASE_BODY,
        verdict: "down",
        reason_tags: ["tone_inappropriate"], // an EXTERNAL-mechanism tag, not INTERNAL
      }),
      writeClient(RATING_ROW, () => (dispatched = true)),
    );
    expect(res.status).toBe(400);
    expect(dispatched).toBe(false);
  });

  it("400s a missing draft_text (never dispatches)", async () => {
    let dispatched = false;
    const { draft_text: _omit, ...rest } = BASE_BODY;
    const res = await handleSubmitDraftFeedbackViaApi(
      jsonReq({ ...rest, verdict: "up" }),
      writeClient(RATING_ROW, () => (dispatched = true)),
    );
    expect(res.status).toBe(400);
    expect(dispatched).toBe(false);
  });

  it("400s a missing case_id", async () => {
    const { case_id: _omit, ...rest } = BASE_BODY;
    const res = await handleSubmitDraftFeedbackViaApi(
      jsonReq({ ...rest, verdict: "up" }),
      writeClient(RATING_ROW),
    );
    expect(res.status).toBe(400);
  });

  it("400s a missing draft_correlation_id", async () => {
    const { draft_correlation_id: _omit, ...rest } = BASE_BODY;
    const res = await handleSubmitDraftFeedbackViaApi(
      jsonReq({ ...rest, verdict: "up" }),
      writeClient(RATING_ROW),
    );
    expect(res.status).toBe(400);
  });

  it("400s an unknown draft_kind", async () => {
    const res = await handleSubmitDraftFeedbackViaApi(
      jsonReq({ ...BASE_BODY, draft_kind: "chat", verdict: "up" }),
      writeClient(RATING_ROW),
    );
    expect(res.status).toBe(400);
  });

  it("400s an invalid verdict", async () => {
    const res = await handleSubmitDraftFeedbackViaApi(
      jsonReq({ ...BASE_BODY, verdict: "meh" }),
      writeClient(RATING_ROW),
    );
    expect(res.status).toBe(400);
  });

  it("400s an unknown feedback kind", async () => {
    let dispatched = false;
    const res = await handleSubmitDraftFeedbackViaApi(
      jsonReq({ kind: "bogus", ...BASE_BODY }),
      writeClient(RATING_ROW, () => (dispatched = true)),
    );
    expect(res.status).toBe(400);
    expect(dispatched).toBe(false);
  });

  // I1 (ADR-0141 fail-closed actor): a client with no actorAccountId is refused by
  // dispatchWrite itself before any network call.
  it("403s when the client carries no actor (dispatchWrite fail-closed)", async () => {
    let dispatched = false;
    const client = apiClient(async () => {
      dispatched = true;
      return new Response(JSON.stringify({ ok: true, data: RATING_ROW }), { status: 200 });
    });
    const res = await handleSubmitDraftFeedbackViaApi(
      jsonReq({ ...BASE_BODY, verdict: "up" }),
      client,
    );
    expect(res.status).toBe(403);
    expect(dispatched).toBe(false);
  });

  it("maps a governed Tool Gate denial (e.g. the rep does not hold the case) to 403", async () => {
    const client = apiClient(async () =>
      new Response(
        JSON.stringify({ ok: false, error: { class: "policy_blocked", message: "denied" } }),
        { status: 200 },
      ),
    REP_ACTOR);
    const res = await handleSubmitDraftFeedbackViaApi(
      jsonReq({ ...BASE_BODY, verdict: "up" }),
      client,
    );
    expect(res.status).toBe(403);
  });
});

// 0.0.4 S09: the "outcome" kind, fired fire-and-forget from GovernedSendModal
// on a successful governed send. Same required trio as the rating branch
// (case_id/draft_correlation_id/draft_kind/draft_text) plus outcome +
// edit_distance_ratio, which is required exactly when outcome is
// "sent_edited" and rejected outright when outcome is "sent_as_is" -- mirrors
// the Python driver's own reject-don't-coerce validation.
describe("handleSubmitDraftFeedbackViaApi (kind: outcome)", () => {
  it("dispatches a sent_as_is outcome with no ratio", async () => {
    let sent: SentDispatch | null = null;
    const res = await handleSubmitDraftFeedbackViaApi(
      jsonReq({ kind: "outcome", ...BASE_BODY, outcome: "sent_as_is" }),
      writeClient({ id: "do_1" }, (s) => (sent = s)),
    );

    expect(res.status).toBe(200);
    const dispatched = sent as SentDispatch | null;
    expect(dispatched?.tool).toBe("toee_feedback");
    expect(dispatched?.action).toBe("record_draft_outcome");
    expect(dispatched?.params).toEqual({
      case_id: "c1",
      draft_correlation_id: "corr-1",
      draft_kind: "sms",
      draft_text: "Your tires are ready.",
      outcome: "sent_as_is",
    });
    expect(dispatched?.actor_account_id).toBe(REP_ACTOR);
  });

  it("dispatches a sent_edited outcome with a ratio", async () => {
    let sent: SentDispatch | null = null;
    const res = await handleSubmitDraftFeedbackViaApi(
      jsonReq({
        kind: "outcome",
        ...BASE_BODY,
        outcome: "sent_edited",
        edit_distance_ratio: 0.35,
      }),
      writeClient({ id: "do_2" }, (s) => (sent = s)),
    );

    expect(res.status).toBe(200);
    const dispatched = sent as SentDispatch | null;
    expect(dispatched?.params).toEqual({
      case_id: "c1",
      draft_correlation_id: "corr-1",
      draft_kind: "sms",
      draft_text: "Your tires are ready.",
      outcome: "sent_edited",
      edit_distance_ratio: 0.35,
    });
  });

  it("400s a sent_edited outcome missing a ratio (never dispatches)", async () => {
    let dispatched = false;
    const res = await handleSubmitDraftFeedbackViaApi(
      jsonReq({ kind: "outcome", ...BASE_BODY, outcome: "sent_edited" }),
      writeClient({ id: "do_3" }, () => (dispatched = true)),
    );
    expect(res.status).toBe(400);
    expect(dispatched).toBe(false);
  });

  // 0.0.5 S27 (FR-33, D11): sent_text -- the text the rep ACTUALLY sent. It is
  // the second operand edit-diff mining span-diffs against draft_text, and
  // before this it was persisted nowhere queryable. Optional on purpose: the
  // outcome POST is fire-and-forget from a send the customer already has, so a
  // caller that does not send it must still record its outcome rather than 400.
  it("forwards sent_text on a sent_edited outcome", async () => {
    let sent: SentDispatch | null = null;
    const res = await handleSubmitDraftFeedbackViaApi(
      jsonReq({
        kind: "outcome",
        ...BASE_BODY,
        outcome: "sent_edited",
        edit_distance_ratio: 0.35,
        sent_text: "Your all-terrain tires are ready.",
      }),
      writeClient({ id: "do_5" }, (s) => (sent = s)),
    );

    expect(res.status).toBe(200);
    const dispatched = sent as SentDispatch | null;
    expect(dispatched?.params).toEqual({
      case_id: "c1",
      draft_correlation_id: "corr-1",
      draft_kind: "sms",
      draft_text: "Your tires are ready.",
      outcome: "sent_edited",
      edit_distance_ratio: 0.35,
      sent_text: "Your all-terrain tires are ready.",
    });
  });

  it("400s a sent_as_is outcome carrying a sent_text (never dispatches)", async () => {
    // "Nothing was edited" and "here is what the edit produced" cannot both be
    // true -- the same reject-don't-coerce rule the ratio follows, enforced here
    // so a malformed request 400s instead of round-tripping to a 502.
    let dispatched = false;
    const res = await handleSubmitDraftFeedbackViaApi(
      jsonReq({
        kind: "outcome",
        ...BASE_BODY,
        outcome: "sent_as_is",
        sent_text: "Your all-terrain tires are ready.",
      }),
      writeClient({ id: "do_6" }, () => (dispatched = true)),
    );
    expect(res.status).toBe(400);
    expect(dispatched).toBe(false);
  });

  it("400s a non-string sent_text (never dispatches)", async () => {
    let dispatched = false;
    const res = await handleSubmitDraftFeedbackViaApi(
      jsonReq({
        kind: "outcome",
        ...BASE_BODY,
        outcome: "sent_edited",
        edit_distance_ratio: 0.35,
        sent_text: 17,
      }),
      writeClient({ id: "do_7" }, () => (dispatched = true)),
    );
    expect(res.status).toBe(400);
    expect(dispatched).toBe(false);
  });

  it("dispatches a sent_edited outcome with no sent_text at all", async () => {
    // D11's no-backfill position, as behaviour: a caller that predates the
    // column still records its outcome, and mining simply never sees that row.
    let sent: SentDispatch | null = null;
    const res = await handleSubmitDraftFeedbackViaApi(
      jsonReq({
        kind: "outcome",
        ...BASE_BODY,
        outcome: "sent_edited",
        edit_distance_ratio: 0.35,
      }),
      writeClient({ id: "do_8" }, (s) => (sent = s)),
    );

    expect(res.status).toBe(200);
    const dispatched = sent as SentDispatch | null;
    expect(dispatched?.params).not.toHaveProperty("sent_text");
  });

  it("400s a sent_as_is outcome carrying a ratio (never dispatches)", async () => {
    let dispatched = false;
    const res = await handleSubmitDraftFeedbackViaApi(
      jsonReq({
        kind: "outcome",
        ...BASE_BODY,
        outcome: "sent_as_is",
        edit_distance_ratio: 0.1,
      }),
      writeClient({ id: "do_4" }, () => (dispatched = true)),
    );
    expect(res.status).toBe(400);
    expect(dispatched).toBe(false);
  });

  it("400s an unknown outcome value (never dispatches)", async () => {
    let dispatched = false;
    const res = await handleSubmitDraftFeedbackViaApi(
      jsonReq({ kind: "outcome", ...BASE_BODY, outcome: "maybe" }),
      writeClient({ id: "do_5" }, () => (dispatched = true)),
    );
    expect(res.status).toBe(400);
    expect(dispatched).toBe(false);
  });

  it("400s a missing draft_text (never dispatches)", async () => {
    let dispatched = false;
    const { draft_text: _omit, ...rest } = BASE_BODY;
    const res = await handleSubmitDraftFeedbackViaApi(
      jsonReq({ kind: "outcome", ...rest, outcome: "sent_as_is" }),
      writeClient({ id: "do_6" }, () => (dispatched = true)),
    );
    expect(res.status).toBe(400);
    expect(dispatched).toBe(false);
  });

  it("403s when the client carries no actor (dispatchWrite fail-closed)", async () => {
    let dispatched = false;
    const client = apiClient(async () => {
      dispatched = true;
      return new Response(JSON.stringify({ ok: true, data: { id: "do_7" } }), { status: 200 });
    });
    const res = await handleSubmitDraftFeedbackViaApi(
      jsonReq({ kind: "outcome", ...BASE_BODY, outcome: "sent_as_is" }),
      client,
    );
    expect(res.status).toBe(403);
    expect(dispatched).toBe(false);
  });

  it("maps a governed Tool Gate denial to 403", async () => {
    const client = apiClient(
      async () =>
        new Response(
          JSON.stringify({ ok: false, error: { class: "policy_blocked", message: "denied" } }),
          { status: 200 },
        ),
      REP_ACTOR,
    );
    const res = await handleSubmitDraftFeedbackViaApi(
      jsonReq({ kind: "outcome", ...BASE_BODY, outcome: "sent_as_is" }),
      client,
    );
    expect(res.status).toBe(403);
  });
});
