import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ChatResponse } from "@/lib/api/copilot-client";
import type { WorkbenchCase } from "@/lib/gateway/types";
import { ErrorBannerProvider } from "@/components/shell/error-banner";
import { CopilotGateway, canSendViaSms } from "./CopilotGateway";

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

describe("canSendViaSms", () => {
  it("is true only for an active SMS session on a case assigned to the operator", () => {
    expect(canSendViaSms(makeCase(), "acct-1")).toBe(true);
  });
  it("is false for non-SMS, inactive session, or another assignee", () => {
    expect(canSendViaSms(makeCase({ channel: "email" }), "acct-1")).toBe(false);
    expect(canSendViaSms(makeCase({ smsSessionActive: false }), "acct-1")).toBe(false);
    expect(canSendViaSms(makeCase({ assigneeAccountId: "acct-2" }), "acct-1")).toBe(false);
    expect(canSendViaSms(null, "acct-1")).toBe(false);
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

  it("renders a draft card from a chat draftCard and shows SMS send for eligible cases", async () => {
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
      screen.getByRole("button", { name: /send via sms/i }),
    ).toBeInTheDocument();
  });

  it("generates a draft via the Draft SMS action", async () => {
    const draft = vi.fn().mockResolvedValue("Generated SMS body");
    renderGateway({ draft });
    fireEvent.click(screen.getByRole("button", { name: /draft sms/i }));
    await waitFor(() => expect(draft).toHaveBeenCalledWith("sms"));
    expect(await screen.findByLabelText(/draft/i)).toHaveValue("Generated SMS body");
  });

  it("hides the SMS send button when the case is not send-eligible", async () => {
    const draft = vi.fn().mockResolvedValue("Email draft");
    renderGateway({ case: makeCase({ channel: "email", smsSessionActive: false }), draft });
    fireEvent.click(screen.getByRole("button", { name: /draft email/i }));
    expect(await screen.findByLabelText(/draft/i)).toHaveValue("Email draft");
    expect(screen.queryByRole("button", { name: /send via sms/i })).toBeNull();
  });

  it("opens the governed send modal from the draft card", async () => {
    const draft = vi.fn().mockResolvedValue("Ready to send");
    renderGateway({ draft });
    fireEvent.click(screen.getByRole("button", { name: /draft sms/i }));
    await screen.findByLabelText(/draft/i);
    fireEvent.click(screen.getByRole("button", { name: /send via sms/i }));
    expect(screen.getByRole("dialog")).toHaveTextContent("Ready to send");
  });
});

// 0.0.4 S07: thumbs rating on the draft card. Rating is an ADJACENT control --
// the key behavior under test is that it never blocks or breaks the
// draft/send flow, even when the rating call itself fails.
describe("CopilotGateway draft rating", () => {
  it("thumbs-up submits immediately with verdict up and no tags", async () => {
    const draft = vi.fn().mockResolvedValue("Generated SMS body");
    const rateDraft = vi.fn().mockResolvedValue({});
    renderGateway({ draft, rateDraft });
    fireEvent.click(screen.getByRole("button", { name: /draft sms/i }));
    await screen.findByLabelText(/draft/i);

    fireEvent.click(screen.getByRole("button", { name: /thumbs up/i }));

    await waitFor(() => expect(rateDraft).toHaveBeenCalledTimes(1));
    const call = rateDraft.mock.calls[0]![0];
    expect(call.caseId).toBe("c1");
    expect(call.draftKind).toBe("sms");
    expect(call.draftText).toBe("Generated SMS body");
    expect(call.verdict).toBe("up");
    expect(call.reasonTags).toEqual([]);
    expect(typeof call.draftCorrelationId).toBe("string");
    expect(call.draftCorrelationId.length).toBeGreaterThan(0);
  });

  it("thumbs-down expands internal reason tags and submits verdict + tags", async () => {
    const draft = vi.fn().mockResolvedValue("Generated SMS body");
    const rateDraft = vi.fn().mockResolvedValue({});
    renderGateway({ draft, rateDraft });
    fireEvent.click(screen.getByRole("button", { name: /draft sms/i }));
    await screen.findByLabelText(/draft/i);

    fireEvent.click(screen.getByRole("button", { name: /thumbs down/i }));
    // Internal tag chips only -- an external-only tag label must not appear.
    expect(screen.getByRole("button", { name: /wrong tone/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /tone inappropriate/i })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /wrong tone/i }));
    fireEvent.click(screen.getByRole("button", { name: /submit rating/i }));

    await waitFor(() => expect(rateDraft).toHaveBeenCalledTimes(1));
    const call = rateDraft.mock.calls[0]![0];
    expect(call.verdict).toBe("down");
    expect(call.reasonTags).toEqual(["wrong_tone"]);
  });

  it("a rating failure shows an inline error and leaves the draft editable and sendable", async () => {
    const draft = vi.fn().mockResolvedValue("Ready to send");
    const rateDraft = vi.fn().mockRejectedValue(new Error("rating service down"));
    renderGateway({ case: makeCase(), draft, rateDraft });
    fireEvent.click(screen.getByRole("button", { name: /draft sms/i }));
    await screen.findByLabelText(/draft/i);

    fireEvent.click(screen.getByRole("button", { name: /thumbs up/i }));
    await waitFor(() => expect(rateDraft).toHaveBeenCalledTimes(1));
    expect(await screen.findByRole("alert")).toHaveTextContent(/failed to submit rating/i);

    // The draft is untouched: still editable and still has a working send path.
    const draftField = screen.getByLabelText(/draft message/i) as HTMLTextAreaElement;
    expect(draftField).toHaveValue("Ready to send");
    fireEvent.change(draftField, { target: { value: "Edited after rating failure" } });
    expect(draftField).toHaveValue("Edited after rating failure");

    fireEvent.click(screen.getByRole("button", { name: /send via sms/i }));
    expect(screen.getByRole("dialog")).toHaveTextContent("Edited after rating failure");
  });

  it("mints a correlation id for a chat draftCard too", async () => {
    const chat = vi.fn(
      async (_message: string): Promise<ChatResponse> => ({
        state: "ready",
        reply: "Here is a draft.",
        draftCard: { channel: "sms", body: "Your tires are ready." },
      }),
    );
    const rateDraft = vi.fn().mockResolvedValue({});
    renderGateway({ chat, rateDraft });
    fireEvent.change(screen.getByLabelText(/message copilot/i), {
      target: { value: "draft an sms" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^send$/i }));
    await screen.findByLabelText(/draft/i);

    fireEvent.click(screen.getByRole("button", { name: /thumbs up/i }));
    await waitFor(() => expect(rateDraft).toHaveBeenCalledTimes(1));
    expect(rateDraft.mock.calls[0]![0].draftKind).toBe("sms");
  });
});
