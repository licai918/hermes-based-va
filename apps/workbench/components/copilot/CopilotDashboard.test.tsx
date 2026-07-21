import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { WORKBENCH_ROLES, type WorkbenchRoleId } from "@toee/shared";
import type { WorkbenchCase } from "@/lib/gateway/types";
import { ErrorBannerProvider } from "@/components/shell/error-banner";
import * as copilot from "@/lib/api/copilot-client";
import { useSearchParams } from "next/navigation";
import { CopilotDashboard } from "./CopilotDashboard";

// FR-12 (0.0.3 S03): the Simulator's case link deep-links in as ?case=<id>.
// Defaults to no query param; individual tests override the return value.
vi.mock("next/navigation", () => ({
  useSearchParams: vi.fn(() => new URLSearchParams()),
}));

vi.mock("@/lib/api/copilot-client", () => ({
  listCases: vi.fn().mockResolvedValue({ cases: [] }),
  getThread: vi.fn().mockResolvedValue({ case: null, messages: [] }),
  getCaseAuditLog: vi.fn(),
  claimCase: vi.fn(),
  assignCase: vi.fn(),
  resolveCase: vi.fn(),
  setPriority: vi.fn(),
  setContactReason: vi.fn(),
  getPreferences: vi.fn().mockResolvedValue({ preferences: {} }),
  upsertPreference: vi.fn(),
  clearPreference: vi.fn(),
  dismissProposal: vi.fn(),
  draft: vi.fn(),
  chat: vi.fn(),
  sendTextline: vi.fn(),
  normalizeDraft: (x: unknown) => String(x),
  proposalsFromDraft: vi.fn().mockReturnValue([]),
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
  vi.mocked(copilot.getPreferences).mockResolvedValue({ preferences: {} });
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

  it("auto-selects the case named by ?case= (FR-12 Simulator deep link)", async () => {
    vi.mocked(useSearchParams).mockReturnValueOnce(
      new URLSearchParams("case=c9") as unknown as ReturnType<typeof useSearchParams>,
    );
    vi.mocked(copilot.getThread).mockResolvedValue({
      case: makeCase({ caseId: "c9", identitySummary: "Linked Case" }),
      messages: [],
    });
    renderDashboard(WORKBENCH_ROLES.rep);

    await waitFor(() => expect(copilot.getThread).toHaveBeenCalledWith("c9"));
    expect(
      await screen.findByRole("region", { name: /case thread context/i }),
    ).toBeInTheDocument();
  });

  it("fetches customer preferences alongside the thread when a case is selected", async () => {
    vi.mocked(copilot.listCases).mockResolvedValue({
      cases: [makeCase({ caseId: "c9", identitySummary: "Pick Me" })],
    });
    vi.mocked(copilot.getThread).mockResolvedValue({
      case: makeCase({ caseId: "c9", identitySummary: "Pick Me" }),
      messages: [],
    });
    vi.mocked(copilot.getPreferences).mockResolvedValue({
      preferences: { contact_time_preference: "Evenings" },
    });
    renderDashboard(WORKBENCH_ROLES.rep);

    fireEvent.click(await screen.findByRole("button", { name: "Pick Me" }));

    await waitFor(() => expect(copilot.getPreferences).toHaveBeenCalledWith("c9"));
    expect(await screen.findByText("Evenings")).toBeInTheDocument();
  });

  it("refreshes preferences after a correction is saved", async () => {
    vi.mocked(copilot.listCases).mockResolvedValue({
      cases: [makeCase({ caseId: "c9", identitySummary: "Pick Me" })],
    });
    vi.mocked(copilot.getThread).mockResolvedValue({
      case: makeCase({ caseId: "c9", identitySummary: "Pick Me" }),
      messages: [],
    });
    vi.mocked(copilot.getPreferences).mockResolvedValue({ preferences: {} });
    vi.mocked(copilot.upsertPreference).mockResolvedValue({
      slot: "channel_preference",
      value: "sms",
      stored: true,
    });
    renderDashboard(WORKBENCH_ROLES.rep);

    fireEvent.click(await screen.findByRole("button", { name: "Pick Me" }));
    await waitFor(() => expect(copilot.getPreferences).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole("button", { name: /edit preferred channel/i }));
    fireEvent.change(screen.getByLabelText("Preferred channel"), {
      target: { value: "sms" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() =>
      expect(copilot.upsertPreference).toHaveBeenCalledWith("c9", "channel_preference", "sms"),
    );
    await waitFor(() => expect(copilot.getPreferences).toHaveBeenCalledTimes(2));
  });

  it("shows a proposal from a draft's response and Accept routes through the existing preferences write", async () => {
    vi.mocked(copilot.listCases).mockResolvedValue({
      cases: [makeCase({ caseId: "c9", identitySummary: "Pick Me" })],
    });
    vi.mocked(copilot.getThread).mockResolvedValue({
      case: makeCase({ caseId: "c9", identitySummary: "Pick Me" }),
      messages: [],
    });
    vi.mocked(copilot.draft).mockResolvedValue({ draft: { channel: "sms", draft: "ok" } });
    vi.mocked(copilot.proposalsFromDraft).mockReturnValue([
      { slot: "channel_preference", value: "sms" },
    ]);
    vi.mocked(copilot.upsertPreference).mockResolvedValue({
      slot: "channel_preference",
      value: "sms",
      stored: true,
    });
    renderDashboard(WORKBENCH_ROLES.rep);

    fireEvent.click(await screen.findByRole("button", { name: "Pick Me" }));
    await waitFor(() => expect(copilot.getPreferences).toHaveBeenCalledTimes(1));

    fireEvent.click(await screen.findByRole("button", { name: "Draft SMS" }));
    await waitFor(() => expect(copilot.draft).toHaveBeenCalledWith("sms", "c9"));

    expect(
      await screen.findByText('Suggest setting Preferred channel = "sms"'),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /accept preferred channel proposal/i }));

    await waitFor(() =>
      expect(copilot.upsertPreference).toHaveBeenCalledWith("c9", "channel_preference", "sms"),
    );
    await waitFor(() =>
      expect(
        screen.queryByText('Suggest setting Preferred channel = "sms"'),
      ).not.toBeInTheDocument(),
    );
  });

  it("Dismiss clears a proposal without writing any preference", async () => {
    vi.mocked(copilot.listCases).mockResolvedValue({
      cases: [makeCase({ caseId: "c9", identitySummary: "Pick Me" })],
    });
    vi.mocked(copilot.getThread).mockResolvedValue({
      case: makeCase({ caseId: "c9", identitySummary: "Pick Me" }),
      messages: [],
    });
    vi.mocked(copilot.draft).mockResolvedValue({ draft: { channel: "sms", draft: "ok" } });
    vi.mocked(copilot.proposalsFromDraft).mockReturnValue([
      { slot: "channel_preference", value: "sms" },
    ]);
    vi.mocked(copilot.dismissProposal).mockResolvedValue({
      slot: "channel_preference",
      dismissed: true,
    });
    renderDashboard(WORKBENCH_ROLES.rep);

    fireEvent.click(await screen.findByRole("button", { name: "Pick Me" }));
    fireEvent.click(await screen.findByRole("button", { name: "Draft SMS" }));
    await screen.findByText('Suggest setting Preferred channel = "sms"');

    fireEvent.click(screen.getByRole("button", { name: /dismiss preferred channel proposal/i }));

    await waitFor(() =>
      expect(copilot.dismissProposal).toHaveBeenCalledWith("c9", "channel_preference", "sms", undefined),
    );
    await waitFor(() =>
      expect(
        screen.queryByText('Suggest setting Preferred channel = "sms"'),
      ).not.toBeInTheDocument(),
    );
    expect(copilot.upsertPreference).not.toHaveBeenCalled();
  });

  it("clears pending proposals when switching to a different case", async () => {
    vi.mocked(copilot.listCases).mockResolvedValue({
      cases: [
        makeCase({ caseId: "c9", identitySummary: "Pick Me" }),
        makeCase({ caseId: "c10", identitySummary: "Other Case" }),
      ],
    });
    vi.mocked(copilot.getThread).mockImplementation(async (caseId: string) => ({
      case: makeCase({ caseId, identitySummary: caseId === "c9" ? "Pick Me" : "Other Case" }),
      messages: [],
    }));
    vi.mocked(copilot.draft).mockResolvedValue({ draft: { channel: "sms", draft: "ok" } });
    vi.mocked(copilot.proposalsFromDraft).mockReturnValue([
      { slot: "channel_preference", value: "sms" },
    ]);
    renderDashboard(WORKBENCH_ROLES.rep);

    fireEvent.click(await screen.findByRole("button", { name: "Pick Me" }));
    fireEvent.click(await screen.findByRole("button", { name: "Draft SMS" }));
    await screen.findByText('Suggest setting Preferred channel = "sms"');

    fireEvent.click(screen.getByRole("button", { name: "Other Case" }));
    await waitFor(() => expect(copilot.getThread).toHaveBeenCalledWith("c10"));
    expect(
      screen.queryByText('Suggest setting Preferred channel = "sms"'),
    ).not.toBeInTheDocument();
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
