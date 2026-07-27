import { describe, expect, it } from "vitest";
import { HermesApiClient } from "../../gateway/hermes-api-client";
import { handleSubmitInteractionReviewViaApi } from "./review";

// 0.0.4 S04: submit_interaction_review's write is asserted at the HTTP-client seam
// -- the dispatched { tool, action, params } envelope, actor attribution, and body
// validation -- mirroring cases.test.ts's handleAssignViaApi coverage. The ROLE
// boundary for this write is enforced at the BFF route-PREFIX gate
// (/api/copilot/audit/* -> withSession -> canAccess), proven in
// lib/auth/access.test.ts, not inside this handler -- see the module docstring in
// ./review.ts and the quality-feedback S04 brief.

type SentDispatch = {
  tool: string;
  action: string;
  params: Record<string, unknown>;
  actor_account_id?: string;
};

const WRITE_ACTOR = "seed-supervisor";

function jsonReq(body: unknown): Request {
  return new Request("http://localhost/api/copilot/audit/review", {
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

const REVIEW_ROW = {
  id: "irev_1",
  subject_kind: "auto_handled_record",
  subject_id: "rec-1",
  verdict: "fail",
  reason_tags: ["factual_error"],
  comment: "wrong answer",
  reviewer_account_id: WRITE_ACTOR,
  created_at: "2026-06-01T12:00:00+00:00",
};

// Captures the dispatched envelope and returns REVIEW_ROW-shaped data.
function writeClient(
  data: unknown,
  capture?: (sent: SentDispatch) => void,
): HermesApiClient {
  return apiClient(async (_url, init) => {
    const sent = JSON.parse(init.body as string) as SentDispatch;
    capture?.(sent);
    return new Response(JSON.stringify({ ok: true, data }), { status: 200 });
  }, WRITE_ACTOR);
}

describe("handleSubmitInteractionReviewViaApi", () => {
  it("dispatches a fail review with tags + comment, actor attached", async () => {
    let sent: SentDispatch | null = null;
    const res = await handleSubmitInteractionReviewViaApi(
      jsonReq({
        subject_kind: "auto_handled_record",
        subject_id: "rec-1",
        verdict: "fail",
        reason_tags: ["factual_error"],
        comment: "wrong answer",
      }),
      writeClient(REVIEW_ROW, (s) => (sent = s)),
    );

    expect(res.status).toBe(200);
    const body = (await res.json()) as { review: { verdict: string; reasonTags: string[] } };
    expect(body.review.verdict).toBe("fail");
    expect(body.review.reasonTags).toEqual(["factual_error"]);

    const dispatched = sent as SentDispatch | null;
    expect(dispatched?.tool).toBe("toee_feedback");
    expect(dispatched?.action).toBe("submit_interaction_review");
    expect(dispatched?.params).toEqual({
      subject_kind: "auto_handled_record",
      subject_id: "rec-1",
      verdict: "fail",
      reason_tags: ["factual_error"],
      comment: "wrong answer",
    });
    // Actor rides along automatically via the per-profile client (ADR-0141).
    expect(dispatched?.actor_account_id).toBe(WRITE_ACTOR);
  });

  it("dispatches a pass review with empty reason_tags and no comment key", async () => {
    let sent: SentDispatch | null = null;
    const res = await handleSubmitInteractionReviewViaApi(
      jsonReq({
        subject_kind: "sales_outreach_case",
        subject_id: "case-1",
        verdict: "pass",
      }),
      writeClient(
        {
          ...REVIEW_ROW,
          subject_kind: "sales_outreach_case",
          subject_id: "case-1",
          verdict: "pass",
          reason_tags: [],
          comment: null,
        },
        (s) => (sent = s),
      ),
    );

    expect(res.status).toBe(200);
    const dispatched = sent as SentDispatch | null;
    expect(dispatched?.params).toEqual({
      subject_kind: "sales_outreach_case",
      subject_id: "case-1",
      verdict: "pass",
      reason_tags: [],
    });
  });

  it("400s a fail verdict with no reason tags (never dispatches)", async () => {
    let dispatched = false;
    const res = await handleSubmitInteractionReviewViaApi(
      jsonReq({ subject_kind: "auto_handled_record", subject_id: "rec-1", verdict: "fail" }),
      writeClient(REVIEW_ROW, () => (dispatched = true)),
    );
    expect(res.status).toBe(400);
    expect(dispatched).toBe(false);
  });

  it("400s an unknown reason tag (never dispatches)", async () => {
    let dispatched = false;
    const res = await handleSubmitInteractionReviewViaApi(
      jsonReq({
        subject_kind: "auto_handled_record",
        subject_id: "rec-1",
        verdict: "fail",
        reason_tags: ["wrong_tone"], // an INTERNAL-mechanism tag, not EXTERNAL
      }),
      writeClient(REVIEW_ROW, () => (dispatched = true)),
    );
    expect(res.status).toBe(400);
    expect(dispatched).toBe(false);
  });

  it("400s an unknown subject_kind", async () => {
    const res = await handleSubmitInteractionReviewViaApi(
      jsonReq({ subject_kind: "case", subject_id: "rec-1", verdict: "pass" }),
      writeClient(REVIEW_ROW),
    );
    expect(res.status).toBe(400);
  });

  it("400s a missing subject_id", async () => {
    const res = await handleSubmitInteractionReviewViaApi(
      jsonReq({ subject_kind: "auto_handled_record", verdict: "pass" }),
      writeClient(REVIEW_ROW),
    );
    expect(res.status).toBe(400);
  });

  it("400s an invalid verdict", async () => {
    const res = await handleSubmitInteractionReviewViaApi(
      jsonReq({ subject_kind: "auto_handled_record", subject_id: "rec-1", verdict: "meh" }),
      writeClient(REVIEW_ROW),
    );
    expect(res.status).toBe(400);
  });

  // I1 (ADR-0141 fail-closed actor): a client with no actorAccountId is refused by
  // dispatchWrite itself before any network call -- defense-in-depth mirroring
  // cases.test.ts's "governed case writes require an actor" block.
  it("403s when the client carries no actor (dispatchWrite fail-closed)", async () => {
    let dispatched = false;
    const client = apiClient(async () => {
      dispatched = true;
      return new Response(JSON.stringify({ ok: true, data: REVIEW_ROW }), { status: 200 });
    });
    const res = await handleSubmitInteractionReviewViaApi(
      jsonReq({ subject_kind: "auto_handled_record", subject_id: "rec-1", verdict: "pass" }),
      client,
    );
    expect(res.status).toBe(403);
    expect(dispatched).toBe(false);
  });

  it("maps a governed Tool Gate denial to its per-class status", async () => {
    const client = apiClient(async () =>
      new Response(
        JSON.stringify({ ok: false, error: { class: "policy_blocked", message: "denied" } }),
        { status: 200 },
      ),
    WRITE_ACTOR);
    const res = await handleSubmitInteractionReviewViaApi(
      jsonReq({ subject_kind: "auto_handled_record", subject_id: "rec-1", verdict: "pass" }),
      client,
    );
    expect(res.status).toBe(403);
  });
});
