import { describe, expect, it } from "vitest";
import { HermesApiClient } from "../../gateway/hermes-api-client";
import { handleListDeadLettersViaApi, handleReplayJobViaApi } from "./dead-letter";

function apiClient(
  fetchImpl: (url: string, init: RequestInit) => Promise<Response>,
  actorAccountId: string | undefined = "seed-supervisor",
): HermesApiClient {
  return new HermesApiClient({
    baseUrl: "http://admin.internal",
    token: "tok",
    actorAccountId,
    fetchImpl,
  });
}

type SentDispatch = {
  tool: string;
  action: string;
  params: Record<string, unknown>;
  actor_account_id?: string;
};

function dispatchResponse(data: unknown): Response {
  return new Response(JSON.stringify({ ok: true, data }), { status: 200 });
}

function deniedResponse(errorClass: string, message = "denied"): Response {
  return new Response(
    JSON.stringify({ ok: false, error: { class: errorClass, message } }),
    { status: 200 },
  );
}

function rawJob(overrides: Record<string, unknown> = {}) {
  return {
    job_id: "job_1",
    type: "agent_turn",
    payload_summary: { event_id: "evt-1" },
    attempts: 3,
    max_attempts: 3,
    last_error: "OutboundSendBurned: provider refused",
    run_at: "2026-07-20T03:00:00+00:00",
    created_at: "2026-07-20T02:00:00+00:00",
    updated_at: "2026-07-20T03:01:00+00:00",
    replayable: true,
    replay_blocked_reason: null,
    outbound: { status: "failed", skip_count: 0, last_error: "502" },
    ...overrides,
  };
}

function rawOutbound(overrides: Record<string, unknown> = {}) {
  return {
    bucket: "send_failed",
    slot: "opt-out",
    idempotency_key: "no-job:evt-stop:opt-out",
    job_id: null,
    event_id: "evt-stop",
    conversation_id: "conv-1",
    channel: "simpletexting_sms",
    status: "failed",
    skip_count: 0,
    last_error: "refused",
    created_at: "2026-07-20T02:00:00+00:00",
    updated_at: "2026-07-20T02:00:00+00:00",
    ...overrides,
  };
}

describe("handleListDeadLettersViaApi (0.0.4 S05, FR-13)", () => {
  it("dispatches list_dead_letters and maps both lists onto camelCase", async () => {
    let captured: SentDispatch | null = null;
    const client = apiClient(async (_url, init) => {
      captured = JSON.parse(init.body as string) as SentDispatch;
      return dispatchResponse({ jobs: [rawJob()], outbound: [rawOutbound()] });
    });

    const res = await handleListDeadLettersViaApi(client);
    expect(res.status).toBe(200);
    const body = (await res.json()) as {
      jobs: Record<string, unknown>[];
      outbound: Record<string, unknown>[];
    };

    expect(body.jobs[0]).toEqual({
      jobId: "job_1",
      type: "agent_turn",
      payloadSummary: { event_id: "evt-1" },
      attempts: 3,
      maxAttempts: 3,
      lastError: "OutboundSendBurned: provider refused",
      runAt: "2026-07-20T03:00:00+00:00",
      createdAt: "2026-07-20T02:00:00+00:00",
      updatedAt: "2026-07-20T03:01:00+00:00",
      replayable: true,
      replayBlockedReason: null,
      outbound: { status: "failed", skipCount: 0, lastError: "502" },
    });
    // The compliance row: an opt-out confirmation that never reached a customer
    // who IS opted out. No job at all -- the slot is how it is told apart.
    expect(body.outbound[0]).toMatchObject({
      bucket: "send_failed",
      slot: "opt-out",
      jobId: null,
      eventId: "evt-stop",
    });

    const sent = captured as SentDispatch | null;
    expect(sent?.tool).toBe("toee_job_queue");
    expect(sent?.action).toBe("list_dead_letters");
    expect(sent?.params).toEqual({});
  });

  it("maps a job that never reached delivery (outbound null) without complaining", async () => {
    const client = apiClient(async () =>
      dispatchResponse({ jobs: [rawJob({ outbound: null })], outbound: [] }),
    );
    const body = (await (await handleListDeadLettersViaApi(client)).json()) as {
      jobs: { outbound: unknown }[];
    };
    expect(body.jobs).toHaveLength(1);
    expect(body.jobs[0]?.outbound).toBeNull();
  });

  it("502s rather than defaulting a missing `replayable` to true", async () => {
    // A backend shape change must not silently re-open replay for a blocked type.
    const job: Record<string, unknown> = rawJob({ type: "l6_review" });
    delete job.replayable;
    const client = apiClient(async () => dispatchResponse({ jobs: [job], outbound: [] }));

    expect((await handleListDeadLettersViaApi(client)).status).toBe(502);
  });

  it("maps the replay audit tail, and tolerates a backend without one", async () => {
    // Fix wave 1, finding 3: `job_replayed` is written with target_type='job'
    // and every other workbench audit view is case- or record-scoped, so this
    // list is the only place a replay's provenance can be seen.
    const client = apiClient(async () =>
      dispatchResponse({
        jobs: [],
        outbound: [],
        recent_replays: [
          {
            job_id: "job_1",
            type: "retention",
            account_id: "acct_super",
            actor_username: "super@toee",
            created_at: "2026-07-21T09:00:00+00:00",
          },
        ],
      }),
    );
    const body = (await (await handleListDeadLettersViaApi(client)).json()) as {
      recentReplays: Record<string, unknown>[];
    };
    expect(body.recentReplays[0]).toEqual({
      jobId: "job_1",
      type: "retention",
      accountId: "acct_super",
      actorUsername: "super@toee",
      createdAt: "2026-07-21T09:00:00+00:00",
    });

    // Unlike `replayable`, a missing provenance list is NOT a 502: it cannot
    // re-open a blocked action, and the mock driver has no audit log at all.
    const mock = apiClient(async () => dispatchResponse({ jobs: [], outbound: [] }));
    const empty = (await (await handleListDeadLettersViaApi(mock)).json()) as {
      recentReplays: unknown[];
    };
    expect(empty.recentReplays).toEqual([]);
  });

  it("maps a governed denial to its per-class status (ADR-0104)", async () => {
    const client = apiClient(async () => deniedResponse("policy_blocked"));
    expect((await handleListDeadLettersViaApi(client)).status).toBe(403);
  });
});

describe("handleReplayJobViaApi (0.0.4 S05, FR-13)", () => {
  it("dispatches replay_job with the job id and the SESSION's actor, not a param", async () => {
    let captured: SentDispatch | null = null;
    const client = apiClient(async (_url, init) => {
      captured = JSON.parse(init.body as string) as SentDispatch;
      return dispatchResponse({ job_id: "job_1", type: "retention", status: "queued" });
    });

    const res = await handleReplayJobViaApi(client, "job_1");
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({
      jobId: "job_1",
      type: "retention",
      status: "queued",
    });

    const sent = captured as SentDispatch | null;
    // ADR-0148: the acting account rides the client, never the params.
    expect(sent?.params).toEqual({ job_id: "job_1" });
    expect(sent?.actor_account_id).toBe("seed-supervisor");
  });

  it("is fail-closed on a missing actor (403, and nothing is dispatched)", async () => {
    let called = false;
    // No actorAccountId at all -- note `apiClient(fn, undefined)` would fall back
    // to the parameter DEFAULT, so build the client directly.
    const client = new HermesApiClient({
      baseUrl: "http://admin.internal",
      token: "tok",
      fetchImpl: async () => {
        called = true;
        return dispatchResponse({});
      },
    });

    expect((await handleReplayJobViaApi(client, "job_1")).status).toBe(403);
    expect(called).toBe(false);
  });

  it("404s a missing job id without dispatching", async () => {
    let called = false;
    const client = apiClient(async () => {
      called = true;
      return dispatchResponse({});
    });

    expect((await handleReplayJobViaApi(client, undefined)).status).toBe(404);
    expect(called).toBe(false);
  });

  it("surfaces the l6_review block as a 403 (policy_blocked)", async () => {
    const client = apiClient(async () => deniedResponse("policy_blocked"));
    expect((await handleReplayJobViaApi(client, "job_l6")).status).toBe(403);
  });

  it("accepts the mock backend's null-type unavailable receipt", async () => {
    const client = apiClient(async () =>
      dispatchResponse({ job_id: "job_1", type: null, status: "unavailable" }),
    );
    const body = (await (await handleReplayJobViaApi(client, "job_1")).json()) as {
      type: string | null;
      status: string;
    };
    expect(body).toEqual({ jobId: "job_1", type: null, status: "unavailable" });
  });
});
