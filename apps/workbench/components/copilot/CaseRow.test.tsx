import { fireEvent, render, screen } from "@testing-library/react";
import type { WorkbenchCase } from "@/lib/gateway/types";
import { CaseRow, formatAssignee } from "./CaseRow";

const NOW = 1_000_000_000_000;

function makeCase(overrides: Partial<WorkbenchCase> = {}): WorkbenchCase {
  return {
    caseId: "c1",
    channel: "sms",
    identitySummary: "Jane Doe (verified)",
    contactReason: "order_status",
    urgent: false,
    status: "in_progress",
    assigneeAccountId: null,
    resolvedByAccountId: null,
    threadId: "t1",
    lastMessagePreview: "Where is my order?",
    toolFailure: false,
    smsSessionActive: true,
    openedAt: NOW - 3_600_000,
    lastActivityAt: NOW - 5 * 60_000,
    ...overrides,
  };
}

type RowOverrides = {
  case?: Partial<WorkbenchCase>;
  accountId?: string;
  selected?: boolean;
  onSelect?: (caseId: string) => void;
  now?: number;
};

function renderRow(props: RowOverrides = {}) {
  const onSelect = vi.fn();
  const { case: caseOverride, ...rest } = props;
  render(
    <table>
      <tbody>
        <CaseRow
          case={makeCase(caseOverride)}
          accountId="acct-1"
          selected={false}
          onSelect={onSelect}
          now={NOW}
          {...rest}
        />
      </tbody>
    </table>,
  );
  return { onSelect };
}

describe("formatAssignee", () => {
  it("labels the current account as Mine", () => {
    expect(formatAssignee("acct-1", "acct-1")).toBe("Mine");
  });
  it("labels a null assignee as Unassigned", () => {
    expect(formatAssignee(null, "acct-1")).toBe("Unassigned");
  });
  it("shows another account's id verbatim", () => {
    expect(formatAssignee("acct-9", "acct-1")).toBe("acct-9");
  });
});

describe("CaseRow", () => {
  it("renders the v1 queue columns", () => {
    renderRow({ case: { assigneeAccountId: "acct-1" } });
    expect(screen.getByText("SMS")).toBeInTheDocument();
    expect(screen.getByText(/Jane Doe/)).toBeInTheDocument();
    expect(screen.getByText("order_status")).toBeInTheDocument();
    expect(screen.getByText("In progress")).toBeInTheDocument();
    expect(screen.getByText("Mine")).toBeInTheDocument();
    expect(screen.getByText("Where is my order?")).toBeInTheDocument();
    expect(screen.getByText("5m ago")).toBeInTheDocument();
  });

  it("shows an urgent marker only for urgent cases", () => {
    const { onSelect } = renderRow({ case: { urgent: true } });
    expect(screen.getByText(/urgent/i)).toBeInTheDocument();
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("hides the urgent marker for non-urgent cases", () => {
    renderRow({ case: { urgent: false } });
    expect(screen.queryByText(/urgent/i)).toBeNull();
  });

  it("shows a tool-failure marker when the case has a tool failure", () => {
    renderRow({ case: { toolFailure: true } });
    expect(screen.getByText(/tool failure/i)).toBeInTheDocument();
  });

  it("selects the case when its row button is clicked", () => {
    const { onSelect } = renderRow({ case: { caseId: "c42" } });
    fireEvent.click(screen.getByRole("button", { name: /Jane Doe/ }));
    expect(onSelect).toHaveBeenCalledWith("c42");
  });

  it("marks the selected row as pressed", () => {
    renderRow({ selected: true });
    expect(screen.getByRole("button", { name: /Jane Doe/ })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });
});
