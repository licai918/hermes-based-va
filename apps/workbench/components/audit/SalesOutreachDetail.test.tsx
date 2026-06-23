import { render, screen } from "@testing-library/react";
import type { WorkbenchCase } from "@/lib/gateway/types";
import { SalesOutreachDetail } from "./SalesOutreachDetail";

const CASE: WorkbenchCase = {
  caseId: "case-1",
  channel: "email",
  identitySummary: "Acme Corp (sales)",
  contactReason: "sales_outreach",
  urgent: true,
  status: "open",
  assigneeAccountId: null,
  resolvedByAccountId: null,
  threadId: "t1",
  lastMessagePreview: "We'd like to sell you solar panels.",
  toolFailure: false,
  smsSessionActive: false,
  openedAt: Date.now() - 3 * 60 * 60_000,
  lastActivityAt: Date.now() - 30 * 60_000,
};

function stubFetch(body: unknown, status = 200) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status })),
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("SalesOutreachDetail", () => {
  it("renders read-only case metadata", async () => {
    stubFetch({ case: CASE });
    render(<SalesOutreachDetail caseId="case-1" />);

    expect(await screen.findByText("Acme Corp (sales)")).toBeInTheDocument();
    expect(screen.getByText("Email")).toBeInTheDocument();
    expect(screen.getByText("sales_outreach")).toBeInTheDocument();
    expect(screen.getByText("Open")).toBeInTheDocument();
    expect(screen.getByText(/urgent/i)).toBeInTheDocument();
    expect(
      screen.getByText("We'd like to sell you solar panels."),
    ).toBeInTheDocument();
  });

  it("shows a friendly not-found state on 404", async () => {
    stubFetch({ error: "not found" }, 404);
    render(<SalesOutreachDetail caseId="missing" />);
    expect(await screen.findByText(/not found/i)).toBeInTheDocument();
    expect(screen.queryByText("Acme Corp (sales)")).toBeNull();
  });
});
