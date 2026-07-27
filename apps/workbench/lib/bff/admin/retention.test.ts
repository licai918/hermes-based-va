import { describe, expect, it } from "vitest";
import { HermesApiClient } from "../../gateway/hermes-api-client";
import { handleGetRetentionStatusViaApi, handleTriggerRetentionSweepViaApi } from "./retention";

function apiClient(
  fetchImpl: (url: string, init: RequestInit) => Promise<Response>,
  actorAccountId: string | undefined = "seed-supervisor",
): HermesApiClient {
  return new HermesApiClient({
    baseUrl: "http://copilot.internal",
    token: "tok",
    actorAccountId,
    fetchImpl,
  });
}

type SentDispatch = { tool: string; action: string; params: Record<string, unknown> };

function dispatchResponse(data: unknown): Response {
  return new Response(JSON.stringify({ ok: true, data }), { status: 200 });
}

function rawStatus(overrides: Record<string, unknown> = {}) {
  return {
    last_run_at: "2026-07-20T03:00:00.000000+00:00",
    counts: { verified: 3, provisional: 5 },
    total_deleted: 8,
    windows_days: { verified: 730, provisional: 90 },
    ...overrides,
  };
}

describe("handleGetRetentionStatusViaApi", () => {
  it("dispatches get_retention_status with no params and maps every field", async () => {
    let captured: SentDispatch | null = null;
    const client = apiClient(async (_url, init) => {
      captured = JSON.parse(init.body as string) as SentDispatch;
      return dispatchResponse(rawStatus());
    });

    const res = await handleGetRetentionStatusViaApi(client);
    expect(res.status).toBe(200);
    const body = (await res.json()) as Record<string, unknown>;

    expect(body).toEqual({
      lastRunAt: "2026-07-20T03:00:00.000000+00:00",
      counts: { verified: 3, provisional: 5 },
      totalDeleted: 8,
      windowsDays: { verified: 730, provisional: 90 },
    });

    const sent = captured as SentDispatch | null;
    expect(sent?.tool).toBe("toee_retention");
    expect(sent?.action).toBe("get_retention_status");
    expect(sent?.params).toEqual({});
  });

  it("maps a never-run status (lastRunAt null) without treating it as malformed", async () => {
    const client = apiClient(async () =>
      dispatchResponse(
        rawStatus({ last_run_at: null, counts: { verified: 0, provisional: 0 }, total_deleted: 0 }),
      ),
    );
    const res = await handleGetRetentionStatusViaApi(client);
    const body = (await res.json()) as { lastRunAt: string | null; totalDeleted: number };
    expect(body.lastRunAt).toBeNull();
    expect(body.totalDeleted).toBe(0);
  });

  it("maps a governed denial to its per-class status (ADR-0104)", async () => {
    const res = await handleGetRetentionStatusViaApi(
      apiClient(
        async () =>
          new Response(
            JSON.stringify({ ok: false, error: { class: "policy_blocked", message: "no" } }),
            { status: 200 },
          ),
      ),
    );
    expect(res.status).toBe(403);
  });

  it("rejects a malformed payload rather than passing it through", async () => {
    const client = apiClient(async () => dispatchResponse({ counts: "not an object" }));
    const res = await handleGetRetentionStatusViaApi(client);
    expect(res.status).toBe(502);
  });
});

// 0.0.4 S04 (FR-11): the trigger enqueues a `retention` job instead of sweeping
// inline, so its response is a job receipt. The counts still come from
// get_retention_status (the sweep's own audit row) -- see the describe above.
describe("handleTriggerRetentionSweepViaApi", () => {
  function rawQueued(overrides: Record<string, unknown> = {}) {
    return { job_id: "job_abc123", status: "queued", ...overrides };
  }

  it("dispatchWrites enqueue_retention_sweep with no params and maps the receipt", async () => {
    let captured: SentDispatch | null = null;
    const client = apiClient(async (_url, init) => {
      captured = JSON.parse(init.body as string) as SentDispatch;
      return dispatchResponse(rawQueued());
    });

    const res = await handleTriggerRetentionSweepViaApi(client);
    expect(res.status).toBe(200);
    const body = (await res.json()) as Record<string, unknown>;

    expect(body).toEqual({ jobId: "job_abc123", status: "queued" });

    const sent = captured as SentDispatch | null;
    expect(sent?.tool).toBe("toee_retention");
    // NOT trigger_retention_sweep: the sweep runs on the background worker now.
    expect(sent?.action).toBe("enqueue_retention_sweep");
    expect(sent?.params).toEqual({});
  });

  it("refuses a write with no attributed actor before the network call (ADR-0141)", async () => {
    // Empty string, not undefined -- a default TS parameter treats an explicit
    // `undefined` argument as "use the default", so this is the actual way to
    // exercise HermesApiClient's falsy actorAccountId check here.
    const client = apiClient(async () => dispatchResponse(rawQueued()), "");
    const res = await handleTriggerRetentionSweepViaApi(client);
    expect(res.status).toBe(403);
  });

  it("a backend with no durable queue reports a null job id, not a fabricated one", async () => {
    // The mock twin's shape (there is no `job` table behind TOOL_BACKEND=mock).
    const client = apiClient(async () =>
      dispatchResponse(rawQueued({ job_id: null, status: "unavailable" })),
    );
    const res = await handleTriggerRetentionSweepViaApi(client);
    const body = (await res.json()) as { jobId: string | null; status: string };
    expect(body).toEqual({ jobId: null, status: "unavailable" });
  });
});
