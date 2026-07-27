import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { RetentionPanel } from "./RetentionPanel";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

const STATUS = {
  lastRunAt: null,
  counts: { verified: 0, provisional: 0 },
  totalDeleted: 0,
  windowsDays: { verified: 730, provisional: 90 },
};

const QUEUED_CAPTION = /Sweep queued/;

describe("RetentionPanel", () => {
  afterEach(() => vi.unstubAllGlobals());

  // 0.0.4 S04 fix wave 1, finding 6: the caption tells the supervisor to Refresh,
  // so it must not survive the Refresh that resolves it.
  it("clears the queued caption once the refresh it asks for completes", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      if (method === "POST") return jsonResponse({ jobId: "job_1", status: "queued" });
      void input;
      return jsonResponse(STATUS);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<RetentionPanel />);
    expect(await screen.findByRole("button", { name: "Run sweep now" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Run sweep now" }));
    expect(await screen.findByText(QUEUED_CAPTION)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Refresh status" }));
    // The panel renders "Loading…" (and nothing else) while a load is in flight,
    // so wait for it to COME BACK before asserting -- otherwise the assertion
    // passes on the loading state and never sees the resolved caption at all.
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    await screen.findByRole("button", { name: "Run sweep now" });
    expect(screen.queryByText(QUEUED_CAPTION)).toBeNull();
  });

  it("keeps the caption when the refresh itself fails (nothing was resolved)", async () => {
    let loads = 0;
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if ((init?.method ?? "GET") === "POST") {
        return jsonResponse({ jobId: "job_1", status: "queued" });
      }
      loads += 1;
      return loads === 1 ? jsonResponse(STATUS) : jsonResponse({ detail: "boom" }, 502);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<RetentionPanel />);
    expect(await screen.findByRole("button", { name: "Run sweep now" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Run sweep now" }));
    expect(await screen.findByText(QUEUED_CAPTION)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Refresh status" }));
    await screen.findByRole("alert");
    expect(screen.getByText(QUEUED_CAPTION)).toBeInTheDocument();
  });
});
