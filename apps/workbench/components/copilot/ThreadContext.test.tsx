import { fireEvent, render, screen } from "@testing-library/react";
import { WORKBENCH_ROLES, type WorkbenchRoleId } from "@toee/shared";
import type { ThreadMessage, WorkbenchCase } from "@/lib/gateway/types";
import { ThreadContext } from "./ThreadContext";

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
    lastMessagePreview: "hi",
    toolFailure: false,
    smsSessionActive: true,
    openedAt: NOW - 3_600_000,
    lastActivityAt: NOW - 60_000,
    ...overrides,
  };
}

function makeMessages(): ThreadMessage[] {
  return [
    {
      messageId: "m1",
      threadId: "t1",
      at: NOW - 7_200_000,
      author: "customer",
      channel: "sms",
      body: "Earlier auto-handled question",
      autoHandled: true,
      activeCaseSegment: false,
    },
    {
      messageId: "m2",
      threadId: "t1",
      at: NOW - 60_000,
      author: "workbench",
      channel: "sms",
      body: "Agent reply in the active case",
      autoHandled: false,
      activeCaseSegment: true,
    },
  ];
}

type ThreadOverrides = {
  case?: Partial<WorkbenchCase>;
  messages?: ThreadMessage[];
  accountId?: string;
  role?: WorkbenchRoleId;
  now?: number;
};

function renderThread(props: ThreadOverrides = {}) {
  const handlers = {
    onClaim: vi.fn(),
    onResolve: vi.fn(),
    onSetPriority: vi.fn(),
    onSetContactReason: vi.fn(),
    onAssign: vi.fn(),
  };
  const { case: caseOverride, messages, role, ...rest } = props;
  render(
    <ThreadContext
      case={makeCase(caseOverride)}
      messages={messages ?? makeMessages()}
      accountId="acct-1"
      role={role ?? WORKBENCH_ROLES.rep}
      now={NOW}
      {...handlers}
      {...rest}
    />,
  );
  return handlers;
}

describe("ThreadContext header", () => {
  it("shows channel, identity, contact reason, status and assignee", () => {
    renderThread({ case: { assigneeAccountId: "acct-1" } });
    expect(screen.getByText("SMS")).toBeInTheDocument();
    expect(screen.getByText(/Jane Doe/)).toBeInTheDocument();
    expect(screen.getByText("order_status")).toBeInTheDocument();
    expect(screen.getByText("In progress")).toBeInTheDocument();
    expect(screen.getByText("Mine")).toBeInTheDocument();
  });

  it("shows Claim only when unassigned and fires onClaim", () => {
    const h = renderThread({ case: { assigneeAccountId: null } });
    fireEvent.click(screen.getByRole("button", { name: /claim/i }));
    expect(h.onClaim).toHaveBeenCalledTimes(1);
  });

  it("hides Claim when the case is already assigned", () => {
    renderThread({ case: { assigneeAccountId: "acct-1" } });
    expect(screen.queryByRole("button", { name: /claim/i })).toBeNull();
  });

  it("fires onResolve when Resolve is clicked", () => {
    const h = renderThread({ case: { assigneeAccountId: "acct-1" } });
    fireEvent.click(screen.getByRole("button", { name: /resolve/i }));
    expect(h.onResolve).toHaveBeenCalledTimes(1);
  });

  it("hides Resolve once the case is resolved", () => {
    renderThread({ case: { status: "resolved", assigneeAccountId: "acct-1" } });
    expect(screen.queryByRole("button", { name: /resolve/i })).toBeNull();
  });

  it("edits the contact reason inline", () => {
    const h = renderThread();
    fireEvent.click(screen.getByRole("button", { name: /edit reason/i }));
    fireEvent.change(screen.getByLabelText(/contact reason/i), {
      target: { value: "billing" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
    expect(h.onSetContactReason).toHaveBeenCalledWith("billing");
  });

  it("hides supervisor-only priority + assign controls from reps", () => {
    renderThread({ role: WORKBENCH_ROLES.rep });
    expect(screen.queryByRole("button", { name: /urgent/i })).toBeNull();
    expect(screen.queryByLabelText(/assign to account/i)).toBeNull();
  });

  it("lets supervisors toggle priority and assign", () => {
    const h = renderThread({
      role: WORKBENCH_ROLES.supervisor,
      case: { urgent: false },
    });
    fireEvent.click(screen.getByRole("button", { name: /mark urgent/i }));
    expect(h.onSetPriority).toHaveBeenCalledWith(true);

    fireEvent.change(screen.getByLabelText(/assign to account/i), {
      target: { value: "acct-7" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^assign$/i }));
    expect(h.onAssign).toHaveBeenCalledWith("acct-7");
  });
});

describe("ThreadContext timeline", () => {
  it("renders each message with an author label and body", () => {
    renderThread();
    expect(screen.getByText("Earlier auto-handled question")).toBeInTheDocument();
    expect(screen.getByText("Agent reply in the active case")).toBeInTheDocument();
    expect(screen.getByText(/customer/i)).toBeInTheDocument();
    expect(screen.getByText(/workbench/i)).toBeInTheDocument();
  });

  it("de-emphasizes prior auto-handled turns and highlights the active segment", () => {
    renderThread();
    const auto = screen
      .getByText("Earlier auto-handled question")
      .closest("li");
    const active = screen
      .getByText("Agent reply in the active case")
      .closest("li");
    expect(auto).toHaveAttribute("data-auto-handled", "true");
    expect(active).toHaveAttribute("data-active-segment", "true");
  });

  it("scrolls to the bottom on first load and when new messages arrive near the bottom", () => {
    const handlers = {
      onClaim: vi.fn(),
      onResolve: vi.fn(),
      onSetPriority: vi.fn(),
      onSetContactReason: vi.fn(),
      onAssign: vi.fn(),
    };
    const baseProps = {
      case: makeCase(),
      accountId: "acct-1",
      role: WORKBENCH_ROLES.rep,
      now: NOW,
      ...handlers,
    };
    const { rerender } = render(<ThreadContext {...baseProps} messages={[]} />);
    const list = screen.getByRole("list", { name: /thread timeline/i });
    Object.defineProperty(list, "scrollHeight", { configurable: true, value: 900 });
    Object.defineProperty(list, "clientHeight", { configurable: true, value: 300 });

    rerender(<ThreadContext {...baseProps} messages={makeMessages()} />);
    expect(list.scrollTop).toBe(900);

    list.scrollTop = 0;
    fireEvent.scroll(list);
    rerender(
      <ThreadContext
        {...baseProps}
        messages={[
          ...makeMessages(),
          {
            messageId: "m3",
            threadId: "t1",
            at: NOW,
            author: "customer",
            channel: "sms",
            body: "Latest inbound",
            autoHandled: false,
            activeCaseSegment: true,
          },
        ]}
      />,
    );
    expect(list.scrollTop).toBe(0);

    list.scrollTop = 600;
    fireEvent.scroll(list);
    rerender(
      <ThreadContext
        {...baseProps}
        messages={[
          ...makeMessages(),
          {
            messageId: "m4",
            threadId: "t1",
            at: NOW + 1,
            author: "hermes",
            channel: "sms",
            body: "Another reply",
            autoHandled: false,
            activeCaseSegment: true,
          },
        ]}
      />,
    );
    expect(list.scrollTop).toBe(900);
  });
});
