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
      return jsonResponse({ jobs: [job()], outbound: [] });
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
    const fetchMock = vi.fn(async () => jsonResponse({ jobs: [job()], outbound: [] }));
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
        jsonResponse({
          jobs: [
            job({
              jobId: "job_l6",
              type: "l6_review",
              replayable: false,
              replayBlockedReason: L6_REASON,
            }),
          ],
          outbound: [],
        }),
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
        jsonResponse({
          jobs: [],
          outbound: [
            {
              bucket: "mirror_missing",
              slot: "reply",
              idempotencyKey: "job_2:evt-2:reply",
              jobId: "job_2",
              eventId: "evt-2",
              conversationId: "conv-2",
              channel: "textline_sms",
              status: "sent",
              skipCount: 0,
              lastError: "mirror write failed",
              createdAt: null,
              updatedAt: null,
            },
          ],
        }),
      ),
    );

    render(<DeadLetterPanel />);

    expect(await screen.findByText("mirror_missing")).toBeInTheDocument();
    expect(screen.getByText(/Do not re-send/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Replay" })).toBeNull();
  });

  it("renders the honest empty view", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ jobs: [], outbound: [] })));

    render(<DeadLetterPanel />);

    expect(await screen.findByText("No dead jobs.")).toBeInTheDocument();
    expect(screen.getByText("No stuck sends.")).toBeInTheDocument();
  });
});
