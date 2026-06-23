import { render, screen, within } from "@testing-library/react";
import type { AutoHandledRecord } from "@/lib/gateway/types";
import { AutoHandledList } from "./AutoHandledList";

function record(over: Partial<AutoHandledRecord> = {}): AutoHandledRecord {
  return {
    recordId: "rec-1",
    channel: "sms",
    identitySummary: "Verified: Jane Doe",
    lastMessagePreview: "Thanks!",
    lastActivityAt: Date.now() - 5 * 60_000 - 2_000,
    outcome: "Auto-resolved",
    toolSummary: "order_status lookup",
    toolFailure: false,
    timeline: [],
    toolCalls: [],
    ...over,
  };
}

function stubFetch(body: unknown, status = 200) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status })),
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("AutoHandledList", () => {
  it("renders a row per record linking to its detail page", async () => {
    stubFetch({
      records: [
        record({ recordId: "rec-1", identitySummary: "Verified: Jane Doe" }),
        record({
          recordId: "rec-2",
          identitySummary: "Unmatched caller",
          channel: "voice",
          outcome: "Escalated",
          toolSummary: "escalation",
          lastActivityAt: Date.now() - 2 * 60 * 60_000,
        }),
      ],
    });
    render(<AutoHandledList />);

    const link = await screen.findByRole("link", { name: "Verified: Jane Doe" });
    expect(link).toHaveAttribute(
      "href",
      "/copilot/audit/auto-handled/rec-1",
    );
    expect(screen.getByRole("link", { name: "Unmatched caller" })).toHaveAttribute(
      "href",
      "/copilot/audit/auto-handled/rec-2",
    );

    expect(screen.getByText("SMS")).toBeInTheDocument();
    expect(screen.getByText("Auto-resolved")).toBeInTheDocument();
    expect(screen.getByText("order_status lookup")).toBeInTheDocument();
    expect(screen.getByText("5m ago")).toBeInTheDocument();
    expect(screen.getAllByText("Thanks!")).toHaveLength(2);
  });

  it("shows the tool-failure indicator only on failing rows", async () => {
    stubFetch({
      records: [
        record({ recordId: "ok", identitySummary: "Good row", toolFailure: false }),
        record({ recordId: "bad", identitySummary: "Bad row", toolFailure: true }),
      ],
    });
    render(<AutoHandledList />);

    const badRow = (
      await screen.findByRole("link", { name: "Bad row" })
    ).closest("tr") as HTMLElement;
    expect(within(badRow).getByText(/tool failure/i)).toBeInTheDocument();

    const okRow = screen
      .getByRole("link", { name: "Good row" })
      .closest("tr") as HTMLElement;
    expect(within(okRow).queryByText(/tool failure/i)).toBeNull();
  });

  it("renders an empty state when there are no records", async () => {
    stubFetch({ records: [] });
    render(<AutoHandledList />);
    expect(await screen.findByText(/no auto-handled/i)).toBeInTheDocument();
  });
});
