import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { WORKBENCH_ROLES, type WorkbenchRoleId } from "@toee/shared";
import type { WorkbenchCase } from "@/lib/gateway/types";
import { ErrorBannerProvider } from "@/components/shell/error-banner";
import * as copilot from "@/lib/api/copilot-client";
import { CopilotDashboard } from "./CopilotDashboard";

vi.mock("@/lib/api/copilot-client", () => ({
  listCases: vi.fn().mockResolvedValue({ cases: [] }),
  getThread: vi.fn().mockResolvedValue({ case: null, messages: [] }),
  getCaseAuditLog: vi.fn(),
  claimCase: vi.fn(),
  assignCase: vi.fn(),
  resolveCase: vi.fn(),
  setPriority: vi.fn(),
  setContactReason: vi.fn(),
  draft: vi.fn(),
  chat: vi.fn(),
  sendTextline: vi.fn(),
  normalizeDraft: (x: unknown) => String(x),
}));

const NOW = 1_000_000_000_000;

function makeCase(overrides: Partial<WorkbenchCase> = {}): WorkbenchCase {
  return {
    caseId: "c1",
    channel: "sms",
    identitySummary: "Queue Caller",
    contactReason: "order_status",
    urgent: false,
    status: "open",
    assigneeAccountId: null,
    resolvedByAccountId: null,
    threadId: "t1",
    lastMessagePreview: "hi",
    toolFailure: false,
    smsSessionActive: true,
    openedAt: NOW,
    lastActivityAt: NOW,
    ...overrides,
  };
}

function renderDashboard(role: WorkbenchRoleId = WORKBENCH_ROLES.rep) {
  render(
    <ErrorBannerProvider>
      <CopilotDashboard accountId="acct-1" role={role} />
    </ErrorBannerProvider>,
  );
}

beforeEach(() => {
  vi.mocked(copilot.listCases).mockResolvedValue({ cases: [] });
  vi.mocked(copilot.getThread).mockResolvedValue({
    case: makeCase(),
    messages: [],
  });
});

afterEach(() => vi.clearAllMocks());

describe("CopilotDashboard", () => {
  it("defaults the rep queue to mine_or_unassigned and loads on mount", async () => {
    renderDashboard(WORKBENCH_ROLES.rep);
    await waitFor(() =>
      expect(copilot.listCases).toHaveBeenCalledWith({
        statuses: ["open", "in_progress"],
        assignee: "mine_or_unassigned",
      }),
    );
  });

  it("defaults the supervisor queue to all team", async () => {
    renderDashboard(WORKBENCH_ROLES.supervisor);
    await waitFor(() =>
      expect(copilot.listCases).toHaveBeenCalledWith({
        statuses: ["open", "in_progress"],
        assignee: "all",
      }),
    );
  });

  it("loads the thread context when a queue case is selected", async () => {
    vi.mocked(copilot.listCases).mockResolvedValue({
      cases: [makeCase({ caseId: "c9", identitySummary: "Pick Me" })],
    });
    vi.mocked(copilot.getThread).mockResolvedValue({
      case: makeCase({ caseId: "c9", identitySummary: "Pick Me" }),
      messages: [],
    });
    renderDashboard(WORKBENCH_ROLES.rep);

    fireEvent.click(await screen.findByRole("button", { name: "Pick Me" }));

    await waitFor(() => expect(copilot.getThread).toHaveBeenCalledWith("c9"));
    expect(
      await screen.findByRole("region", { name: /case thread context/i }),
    ).toBeInTheDocument();
  });

  it("polls queue and thread while the tab is visible", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.mocked(copilot.listCases).mockResolvedValue({
      cases: [makeCase({ caseId: "c9", identitySummary: "Pick Me" })],
    });
    renderDashboard(WORKBENCH_ROLES.rep);
    await waitFor(() => expect(copilot.listCases).toHaveBeenCalledTimes(1));

    fireEvent.click(await screen.findByRole("button", { name: "Pick Me" }));
    await waitFor(() => expect(copilot.getThread).toHaveBeenCalledTimes(1));

    vi.advanceTimersByTime(4_000);
    await waitFor(() => expect(copilot.listCases).toHaveBeenCalledTimes(2));
    expect(copilot.getThread).toHaveBeenCalledTimes(2);

    vi.useRealTimers();
  });

  it("pauses polling while the tab is hidden", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    renderDashboard(WORKBENCH_ROLES.rep);
    await waitFor(() => expect(copilot.listCases).toHaveBeenCalledTimes(1));

    Object.defineProperty(document, "hidden", { configurable: true, value: true });
    vi.advanceTimersByTime(4_000);
    expect(copilot.listCases).toHaveBeenCalledTimes(1);

    Object.defineProperty(document, "hidden", { configurable: true, value: false });
    document.dispatchEvent(new Event("visibilitychange"));
    await waitFor(() => expect(copilot.listCases).toHaveBeenCalledTimes(2));

    Object.defineProperty(document, "hidden", { configurable: true, value: false });
    vi.useRealTimers();
  });
});
