import { render, screen } from "@testing-library/react";
import type { WorkbenchCase } from "@/lib/gateway/types";
import { SalesOutreachList } from "./SalesOutreachList";

function wcase(over: Partial<WorkbenchCase>): WorkbenchCase {
  return {
    caseId: "case-1",
    channel: "email",
    identitySummary: "Acme Corp (sales)",
    contactReason: "sales_outreach",
    urgent: false,
    status: "open",
    assigneeAccountId: null,
    resolvedByAccountId: null,
    threadId: "t1",
    lastMessagePreview: "We'd like to sell you...",
    toolFailure: false,
    smsSessionActive: false,
    openedAt: Date.now() - 3 * 60 * 60_000,
    lastActivityAt: Date.now() - 30 * 60_000,
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

describe("SalesOutreachList", () => {
  it("renders a row per case linking to its detail page", async () => {
    stubFetch({
      cases: [
        wcase({ caseId: "case-1", identitySummary: "Acme Corp (sales)" }),
        wcase({
          caseId: "case-2",
          identitySummary: "Beta LLC (sales)",
          channel: "sms",
          status: "in_progress",
        }),
      ],
    });
    render(<SalesOutreachList />);

    const link = await screen.findByRole("link", { name: "Acme Corp (sales)" });
    expect(link).toHaveAttribute("href", "/copilot/audit/sales-outreach/case-1");
    expect(screen.getByRole("link", { name: "Beta LLC (sales)" })).toHaveAttribute(
      "href",
      "/copilot/audit/sales-outreach/case-2",
    );

    expect(screen.getByText("Email")).toBeInTheDocument();
    expect(screen.getAllByText("sales_outreach")).toHaveLength(2);
    expect(screen.getByText("Open")).toBeInTheDocument();
    expect(screen.getByText("In progress")).toBeInTheDocument();
    expect(screen.getByText("case-1")).toBeInTheDocument();
    expect(screen.getByText("case-2")).toBeInTheDocument();
    expect(screen.getAllByText(/We'd like to sell you/)).toHaveLength(2);
  });

  it("renders an empty state when there are no cases", async () => {
    stubFetch({ cases: [] });
    render(<SalesOutreachList />);
    expect(await screen.findByText(/no sales outreach/i)).toBeInTheDocument();
  });
});
