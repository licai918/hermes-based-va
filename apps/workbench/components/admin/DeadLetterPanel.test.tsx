import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { DeadLetterPanel } from "./DeadLetterPanel";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

function job(overrides: Record<string, unknown> = {}) {
  return {
    jobId: "job_1",
    type: "retention",
    payloadSummary: { profile: "internal_copilot" },
    attempts: 3,
    maxAttempts: 3,
    lastError: "boom",
    runAt: null,
    createdAt: null,
    updatedAt: null,
    replayable: true,
    replayBlockedReason: null,
    outbound: null,
    ...overrides,
  };
}

// Every view the panel renders now carries three lists.
function view(overrides: Record<string, unknown> = {}) {
  return { jobs: [], outbound: [], recentReplays: [], ...overrides };
}

const L6_REASON =
  "Replay is blocked for l6_review: the review fork writes a proposal … until proposal dedupe exists.";

describe("DeadLetterPanel (0.0.4 S05, FR-13)", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("replays a job after a confirm and re-reads the view", async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if ((init?.method ?? "GET") === "POST") {
        return jsonResponse({ jobId: "job_1", type: "retention", status: "queued" });
      }
      return jsonResponse(view({ jobs: [job()] }));
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.spyOn(window, "confirm").mockReturnValue(true);

    render(<DeadLetterPanel />);
    fireEvent.click(await screen.findByRole("button", { name: "Replay" }));

    await waitFor(() =>
      expect(
        fetchMock.mock.calls.filter(([, i]) => (i as RequestInit | undefined)?.method === "POST"),
      ).toHaveLength(1),
    );
    const [, init] = fetchMock.mock.calls.find(
      ([, i]) => (i as RequestInit | undefined)?.method === "POST",
    ) as [unknown, RequestInit];
    // No bulk replay in v1: one job id, and no actor in the body (ADR-0148).
    expect(JSON.parse(init.body as string)).toEqual({ jobId: "job_1" });
    expect(await screen.findByText(/Replayed job_1/)).toBeInTheDocument();
  });

  it("does nothing when the operator cancels the confirm", async () => {
    const fetchMock = vi.fn(async () => jsonResponse(view({ jobs: [job()] })));
    vi.stubGlobal("fetch", fetchMock);
    vi.spyOn(window, "confirm").mockReturnValue(false);

    render(<DeadLetterPanel />);
    fireEvent.click(await screen.findByRole("button", { name: "Replay" }));

    expect(
      fetchMock.mock.calls.filter(
        (call) => ((call as unknown[])[1] as RequestInit | undefined)?.method === "POST",
      ),
    ).toHaveLength(0);
  });

  it("disables Replay for an unreplayable type and shows the reason", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse(
          view({
            jobs: [
              job({
                jobId: "job_l6",
                type: "l6_review",
                replayable: false,
                replayBlockedReason: L6_REASON,
              }),
            ],
          }),
        ),
      ),
    );

    render(<DeadLetterPanel />);

    expect(await screen.findByRole("button", { name: "Replay" })).toBeDisabled();
    // The block must be READABLE, not just enforced -- the sanitized 403 from a
    // ToolDriverError (ADR-0136) cannot carry the reason, so the list does.
    expect(screen.getByText(/proposal dedupe/)).toBeInTheDocument();
  });

  it("surfaces a stuck send with what to do about it, and offers no re-send", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse(
          view({
            outbound: [
              {
                bucket: "mirror_missing",
                slot: "reply",
                idempotencyKey: "job_2:evt-2:reply",
                jobId: "job_2",
                eventId: "evt-2",
                conversationId: "conv-2",
                channel: "simpletexting_sms",
                status: "sent",
                skipCount: 0,
                lastError: "mirror write failed",
                createdAt: null,
                updatedAt: null,
              },
            ],
          }),
        ),
      ),
    );

    render(<DeadLetterPanel />);

    expect(await screen.findByText("mirror_missing")).toBeInTheDocument();
    expect(screen.getByText(/Do not re-send/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Replay" })).toBeNull();
  });

  it("refuses to offer a Replay that cannot possibly send (fix wave 1, finding 2)", async () => {
    // The most common dead turn: the model ran, the send FAILED, and the
    // idempotency key is now spent. deliver_once raises OutboundSendBurned on
    // every re-run, so a replay re-runs the model, burns all three attempts,
    // re-dead-letters, and texts the customer nothing.
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse(
          view({
            jobs: [
              job({
                type: "agent_turn",
                outbound: { status: "failed", skipCount: 0, lastError: "502 from provider" },
              }),
            ],
          }),
        ),
      ),
    );

    render(<DeadLetterPanel />);

    expect(await screen.findByRole("button", { name: "Replay" })).toBeDisabled();
    expect(screen.getByText(/Send this reply by hand/)).toBeInTheDocument();
  });

  it("also refuses when the send succeeded but left an error (the mirror case)", async () => {
    // `sent` + a last_error burns the key just the same -- record_skip reports
    // the prior error and deliver_once raises rather than returning False.
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse(
          view({
            jobs: [
              job({
                type: "agent_turn",
                outbound: { status: "sent", skipCount: 1, lastError: "mirror write failed" },
              }),
            ],
          }),
        ),
      ),
    );

    render(<DeadLetterPanel />);

    expect(await screen.findByRole("button", { name: "Replay" })).toBeDisabled();
    expect(screen.getByText(/already spent/)).toBeInTheDocument();
  });

  it("still offers Replay when the job never reached delivery", async () => {
    // `outbound: null` is the state that says a replay will genuinely send.
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse(view({ jobs: [job({ type: "agent_turn" })] }))),
    );

    render(<DeadLetterPanel />);

    expect(await screen.findByRole("button", { name: "Replay" })).toBeEnabled();
  });

  it("shows who replayed what and when (fix wave 1, finding 3)", async () => {
    // FR-13 gate (2): the job_replayed audit row is target_type='job' and every
    // other workbench audit view is case- or record-scoped, so this list is the
    // only UI that can show it -- PAC-3 needed psql without it.
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse(
          view({
            recentReplays: [
              {
                jobId: "job_1",
                type: "retention",
                accountId: "acct_super",
                actorUsername: "super@toee",
                createdAt: "2026-07-21T09:00:00+00:00",
              },
            ],
          }),
        ),
      ),
    );

    render(<DeadLetterPanel />);

    expect(await screen.findByText(/replayed by super@toee/)).toBeInTheDocument();
  });

  it("never says 'No dead jobs.' on a failed load (fix wave 1, finding 4)", async () => {
    // An unconfigured backend is now a 503 rather than an empty view, and the
    // panel must not reassure on top of it.
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse({ error: "Dead-letter backend is not configured" }, 503),
      ),
    );

    render(<DeadLetterPanel />);

    expect(await screen.findByRole("alert")).toHaveTextContent(/not configured/);
    expect(screen.queryByText("No dead jobs.")).toBeNull();
  });

  it("renders the honest empty view", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(view())));

    render(<DeadLetterPanel />);

    expect(await screen.findByText("No dead jobs.")).toBeInTheDocument();
    expect(screen.getByText("No stuck sends.")).toBeInTheDocument();
    expect(screen.getByText("No replays recorded.")).toBeInTheDocument();
  });
});
