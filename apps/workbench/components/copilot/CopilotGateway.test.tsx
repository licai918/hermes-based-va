import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ChatResponse } from "@/lib/api/copilot-client";
import type { WorkbenchCase } from "@/lib/gateway/types";
import { ErrorBannerProvider } from "@/components/shell/error-banner";
import { CopilotGateway, canSendViaTextline } from "./CopilotGateway";

function makeCase(overrides: Partial<WorkbenchCase> = {}): WorkbenchCase {
  return {
    caseId: "c1",
    channel: "sms",
    identitySummary: "Jane Doe",
    contactReason: "order_status",
    urgent: false,
    status: "in_progress",
    assigneeAccountId: "acct-1",
    resolvedByAccountId: null,
    threadId: "t1",
    lastMessagePreview: "hi",
    toolFailure: false,
    smsSessionActive: true,
    openedAt: 1,
    lastActivityAt: 1,
    ...overrides,
  };
}

function renderGateway(props: Partial<Parameters<typeof CopilotGateway>[0]> = {}) {
  const chat =
    props.chat ??
    vi.fn(
      async (_message: string): Promise<ChatResponse> => ({
        state: "ready",
        reply: "Reviewing this case.",
      }),
    );
  const draft = props.draft ?? vi.fn().mockResolvedValue("Drafted reply");
  const onSent = props.onSent ?? vi.fn();
  const { case: caseProp, ...rest } = props;
  render(
    <ErrorBannerProvider>
      <CopilotGateway
        case={caseProp === undefined ? makeCase() : caseProp}
        accountId="acct-1"
        chat={chat}
        draft={draft}
        onSent={onSent}
        {...rest}
      />
    </ErrorBannerProvider>,
  );
  return { chat, draft, onSent };
}

describe("canSendViaTextline", () => {
  it("is true only for an active SMS session on a case assigned to the operator", () => {
    expect(canSendViaTextline(makeCase(), "acct-1")).toBe(true);
  });
  it("is false for non-SMS, inactive session, or another assignee", () => {
    expect(canSendViaTextline(makeCase({ channel: "email" }), "acct-1")).toBe(false);
    expect(canSendViaTextline(makeCase({ smsSessionActive: false }), "acct-1")).toBe(false);
    expect(canSendViaTextline(makeCase({ assigneeAccountId: "acct-2" }), "acct-1")).toBe(false);
    expect(canSendViaTextline(null, "acct-1")).toBe(false);
  });
});

describe("CopilotGateway idle state", () => {
  it("prompts to select a case and offers no drafting when none is selected", () => {
    renderGateway({ case: null });
    expect(screen.getByText(/select a .*case/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/message copilot/i)).toBeNull();
    expect(screen.queryByRole("button", { name: /draft sms/i })).toBeNull();
  });
});

describe("CopilotGateway active state", () => {
  it("sends a chat message and renders the reply", async () => {
    const { chat } = renderGateway();
    fireEvent.change(screen.getByLabelText(/message copilot/i), {
      target: { value: "what's going on?" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^send$/i }));
    await waitFor(() => expect(chat).toHaveBeenCalledWith("what's going on?"));
    expect(await screen.findByText("Reviewing this case.")).toBeInTheDocument();
  });

  it("renders a draft card from a chat draftCard and shows Textline for eligible cases", async () => {
    const chat = vi.fn(
      async (_message: string): Promise<ChatResponse> => ({
        state: "ready",
        reply: "Here is a draft.",
        draftCard: { channel: "sms", body: "Your tires are ready." },
      }),
    );
    renderGateway({ chat });
    fireEvent.change(screen.getByLabelText(/message copilot/i), {
      target: { value: "draft an sms" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^send$/i }));
    const draftField = await screen.findByLabelText(/draft/i);
    expect(draftField).toHaveValue("Your tires are ready.");
    expect(
      screen.getByRole("button", { name: /send via textline/i }),
    ).toBeInTheDocument();
  });

  it("generates a draft via the Draft SMS action", async () => {
    const draft = vi.fn().mockResolvedValue("Generated SMS body");
    renderGateway({ draft });
    fireEvent.click(screen.getByRole("button", { name: /draft sms/i }));
    await waitFor(() => expect(draft).toHaveBeenCalledWith("sms"));
    expect(await screen.findByLabelText(/draft/i)).toHaveValue("Generated SMS body");
  });

  it("hides the Textline button when the case is not send-eligible", async () => {
    const draft = vi.fn().mockResolvedValue("Email draft");
    renderGateway({ case: makeCase({ channel: "email", smsSessionActive: false }), draft });
    fireEvent.click(screen.getByRole("button", { name: /draft email/i }));
    expect(await screen.findByLabelText(/draft/i)).toHaveValue("Email draft");
    expect(screen.queryByRole("button", { name: /send via textline/i })).toBeNull();
  });

  it("opens the governed send modal from the draft card", async () => {
    const draft = vi.fn().mockResolvedValue("Ready to send");
    renderGateway({ draft });
    fireEvent.click(screen.getByRole("button", { name: /draft sms/i }));
    await screen.findByLabelText(/draft/i);
    fireEvent.click(screen.getByRole("button", { name: /send via textline/i }));
    expect(screen.getByRole("dialog")).toHaveTextContent("Ready to send");
  });
});
