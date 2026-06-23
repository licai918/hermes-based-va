import { fireEvent, render, screen } from "@testing-library/react";
import type { WorkbenchCase } from "@/lib/gateway/types";
import { CaseQueue } from "./CaseQueue";
import type { QueueFilter } from "./QueueFilters";

const NOW = 1_000_000_000_000;
const filter: QueueFilter = {
  statuses: ["open", "in_progress"],
  assignee: "mine_or_unassigned",
};

function makeCase(overrides: Partial<WorkbenchCase> = {}): WorkbenchCase {
  return {
    caseId: "c1",
    channel: "sms",
    identitySummary: "Jane Doe",
    contactReason: "order_status",
    urgent: false,
    status: "open",
    assigneeAccountId: null,
    resolvedByAccountId: null,
    threadId: "t1",
    lastMessagePreview: "hello",
    toolFailure: false,
    smsSessionActive: true,
    openedAt: NOW,
    lastActivityAt: NOW,
    ...overrides,
  };
}

function renderQueue(props: Partial<Parameters<typeof CaseQueue>[0]> = {}) {
  const onSelect = vi.fn();
  const onFilterChange = vi.fn();
  render(
    <CaseQueue
      cases={[makeCase()]}
      accountId="acct-1"
      selectedCaseId={null}
      onSelect={onSelect}
      filter={filter}
      onFilterChange={onFilterChange}
      canViewAllTeam={false}
      now={NOW}
      {...props}
    />,
  );
  return { onSelect, onFilterChange };
}

describe("CaseQueue", () => {
  it("renders the filters and a row per case", () => {
    renderQueue({
      cases: [
        makeCase({ caseId: "c1", identitySummary: "First Caller" }),
        makeCase({ caseId: "c2", identitySummary: "Second Caller" }),
      ],
    });
    expect(screen.getByLabelText("Assignee")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "First Caller" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Second Caller" })).toBeInTheDocument();
  });

  it("shows an empty state when there are no cases", () => {
    renderQueue({ cases: [] });
    expect(screen.getByText(/no cases/i)).toBeInTheDocument();
  });

  it("forwards row selection", () => {
    const { onSelect } = renderQueue({
      cases: [makeCase({ caseId: "c9", identitySummary: "Pick Me" })],
    });
    fireEvent.click(screen.getByRole("button", { name: "Pick Me" }));
    expect(onSelect).toHaveBeenCalledWith("c9");
  });

  it("forwards filter changes", () => {
    const { onFilterChange } = renderQueue({ canViewAllTeam: true });
    fireEvent.change(screen.getByLabelText("Assignee"), {
      target: { value: "all" },
    });
    expect(onFilterChange).toHaveBeenCalledWith(
      expect.objectContaining({ assignee: "all" }),
    );
  });
});
