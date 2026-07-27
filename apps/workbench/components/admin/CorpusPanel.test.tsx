import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ErrorBannerProvider } from "@/components/shell/error-banner";
import { CorpusPanel } from "./CorpusPanel";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

function renderPanel() {
  return render(
    <ErrorBannerProvider>
      <CorpusPanel />
    </ErrorBannerProvider>,
  );
}

describe("CorpusPanel", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("loads and renders corpus status on mount", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse({
          status: {
            docCount: 27,
            chunkCount: 167,
            lastIngestAt: "2026-07-01T12:00:00+00:00",
            byType: [
              { pageType: "faq", count: 40 },
              { pageType: "policy", count: 127 },
            ],
          },
        }),
      ),
    );
    renderPanel();

    expect(await screen.findByText("27")).toBeInTheDocument();
    expect(screen.getByText("167")).toBeInTheDocument();
    expect(screen.getByText("2026-07-01T12:00:00+00:00")).toBeInTheDocument();
    expect(screen.getByText("faq")).toBeInTheDocument();
    expect(screen.getByText("policy")).toBeInTheDocument();
  });

  it("shows 'never' when the corpus has no ingest yet", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse({
          status: { docCount: 0, chunkCount: 0, lastIngestAt: null, byType: [] },
        }),
      ),
    );
    renderPanel();
    expect(await screen.findByText("never")).toBeInTheDocument();
  });

  // --- 0.0.4 S04 (FR-11): re-ingest is a real enqueue, not a printed command ---

  it("Re-ingest corpus posts the enqueue and re-reads the status", async () => {
    const fetchMock = vi.fn((_url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        return Promise.resolve(jsonResponse({ jobId: "job_ing1", status: "queued" }));
      }
      return Promise.resolve(
        jsonResponse({
          status: {
            docCount: 0,
            chunkCount: 0,
            lastIngestAt: null,
            byType: [],
            lastIngestJob: {
              jobId: "job_ing1",
              status: "queued",
              attempts: 0,
              lastError: null,
              queuedAt: "2026-07-21T08:00:00+00:00",
              updatedAt: null,
            },
          },
        }),
      );
    });
    vi.stubGlobal("fetch", fetchMock);
    renderPanel();
    await screen.findByText("never");

    fireEvent.click(screen.getByRole("button", { name: /re-ingest corpus/i }));

    await waitFor(() =>
      expect(screen.getByText(/last re-ingest job: queued/i)).toBeInTheDocument(),
    );
    const postCall = fetchMock.mock.calls.find(
      ([, init]) => (init as RequestInit)?.method === "POST",
    );
    expect(postCall?.[0]).toBe("/api/admin/knowledge/reingest");
  });

  it("says so when no re-ingest has ever been queued", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse({
          status: {
            docCount: 0,
            chunkCount: 0,
            lastIngestAt: null,
            byType: [],
            lastIngestJob: null,
          },
        }),
      ),
    );
    renderPanel();
    expect(await screen.findByText(/no re-ingest queued yet/i)).toBeInTheDocument();
  });

  it("surfaces a dead re-ingest job's error instead of hiding it", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse({
          status: {
            docCount: 0,
            chunkCount: 0,
            lastIngestAt: null,
            byType: [],
            lastIngestJob: {
              jobId: "job_ing1",
              status: "dead",
              attempts: 1,
              lastError: "RuntimeError: no corpus artifact to ingest",
              queuedAt: "2026-07-21T08:00:00+00:00",
              updatedAt: "2026-07-21T08:01:00+00:00",
            },
          },
        }),
      ),
    );
    renderPanel();
    expect(await screen.findByText(/no corpus artifact to ingest/i)).toBeInTheDocument();
  });

  it("Refresh status re-fetches the status endpoint", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        status: { docCount: 1, chunkCount: 5, lastIngestAt: null, byType: [] },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    renderPanel();
    await screen.findByText("1");
    expect(fetchMock).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: /refresh status/i }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  });

  it("submits a probe query and renders top-k results", async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        return Promise.resolve(
          jsonResponse({
            results: [
              {
                title: "Return Policy",
                url: "https://example.test/returns",
                snippet: "Tires may be returned within 30 days.",
              },
            ],
          }),
        );
      }
      return Promise.resolve(
        jsonResponse({
          status: { docCount: 0, chunkCount: 0, lastIngestAt: null, byType: [] },
        }),
      );
    });
    vi.stubGlobal("fetch", fetchMock);
    renderPanel();
    await screen.findByText("never");

    fireEvent.change(screen.getByLabelText(/query/i), {
      target: { value: "return policy" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^search$/i }));

    expect(await screen.findByText("Return Policy")).toBeInTheDocument();
    expect(screen.getByText("Tires may be returned within 30 days.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "https://example.test/returns" })).toHaveAttribute(
      "href",
      "https://example.test/returns",
    );

    const postCall = fetchMock.mock.calls.find(([, init]) => (init as RequestInit)?.method === "POST");
    expect(postCall?.[0]).toBe("/api/admin/knowledge/probe");
    expect(JSON.parse((postCall?.[1] as RequestInit).body as string)).toEqual({
      query: "return policy",
    });
  });

  it("shows an inline alert when the probe fails", async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        return Promise.resolve(jsonResponse({ error: "service unavailable" }, 502));
      }
      return Promise.resolve(
        jsonResponse({
          status: { docCount: 0, chunkCount: 0, lastIngestAt: null, byType: [] },
        }),
      );
    });
    vi.stubGlobal("fetch", fetchMock);
    renderPanel();
    await screen.findByText("never");

    fireEvent.change(screen.getByLabelText(/query/i), { target: { value: "anything" } });
    fireEvent.click(screen.getByRole("button", { name: /^search$/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/service unavailable/i);
  });
});
