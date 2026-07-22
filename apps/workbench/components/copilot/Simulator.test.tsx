import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ApiError } from "@/lib/api/http";
import type { ThreadMessage } from "@/lib/gateway/types";
import { ErrorBannerProvider } from "@/components/shell/error-banner";
import * as simulator from "@/lib/api/simulator-client";
import { Simulator } from "./Simulator";

// A promise this test controls the resolution timing of, so it can simulate
// a fetch/send that's still in flight when the user switches phones.
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

vi.mock("@/lib/api/simulator-client", () => ({
  sendSimulatorMessage: vi.fn(),
  getSimulatorThread: vi.fn(),
  linkSimulatorIdentity: vi.fn(),
  sendSimulatorEmail: vi.fn(),
  getSimulatorEmailThread: vi.fn(),
}));

const NOW = 1_000_000_000_000;

function turn(overrides: Partial<ThreadMessage> = {}): ThreadMessage {
  return {
    messageId: "m1",
    threadId: "t1",
    at: NOW - 60_000,
    author: "customer",
    channel: "sms",
    body: "hi",
    autoHandled: false,
    activeCaseSegment: true,
    ...overrides,
  };
}

function renderSimulator() {
  render(
    <ErrorBannerProvider>
      <Simulator now={NOW} />
    </ErrorBannerProvider>,
  );
}

beforeEach(() => {
  vi.mocked(simulator.getSimulatorThread).mockResolvedValue({ caseId: null, messages: [] });
});

afterEach(() => {
  vi.clearAllMocks();
  vi.useRealTimers();
});

describe("Simulator", () => {
  it("loads the thread for the default phone on mount", async () => {
    renderSimulator();
    await waitFor(() =>
      expect(simulator.getSimulatorThread).toHaveBeenCalledWith("+15550001001"),
    );
  });

  it("renders read-back inbound and outbound turns as distinct bubbles", async () => {
    vi.mocked(simulator.getSimulatorThread).mockResolvedValue({
      caseId: null,
      messages: [
        turn({ messageId: "1", author: "customer", body: "Do you have 225/65R17?" }),
        turn({ messageId: "2", author: "hermes", body: "Yes, in stock" }),
      ],
    });
    renderSimulator();

    expect(await screen.findByText("Do you have 225/65R17?")).toBeInTheDocument();
    expect(await screen.findByText("Yes, in stock")).toBeInTheDocument();
    expect(screen.getAllByText(/Customer|Hermes/)).toHaveLength(2);
  });

  it("submitting the composer posts through the simulator ingress", async () => {
    vi.mocked(simulator.sendSimulatorMessage).mockResolvedValue({
      conversationId: "conv-1",
      eventId: "evt-1",
      accepted: true,
    });
    renderSimulator();
    await waitFor(() => expect(simulator.getSimulatorThread).toHaveBeenCalledTimes(1));

    fireEvent.change(screen.getByLabelText("Simulated customer message"), {
      target: { value: "Do you have 225/65R17 in stock?" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() =>
      expect(simulator.sendSimulatorMessage).toHaveBeenCalledWith({
        fromPhone: "+15550001001",
        body: "Do you have 225/65R17 in stock?",
        conversationId: undefined,
      }),
    );
    expect(await screen.findByText(/Accepted/)).toBeInTheDocument();
  });

  it("reuses the conversationId returned by the first send on later sends", async () => {
    vi.mocked(simulator.sendSimulatorMessage).mockResolvedValue({
      conversationId: "conv-1",
      eventId: "evt-1",
      accepted: true,
    });
    renderSimulator();
    await waitFor(() => expect(simulator.getSimulatorThread).toHaveBeenCalledTimes(1));

    fireEvent.change(screen.getByLabelText("Simulated customer message"), {
      target: { value: "first" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(simulator.sendSimulatorMessage).toHaveBeenCalledTimes(1));

    fireEvent.change(screen.getByLabelText("Simulated customer message"), {
      target: { value: "second" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(simulator.sendSimulatorMessage).toHaveBeenCalledTimes(2));

    expect(simulator.sendSimulatorMessage).toHaveBeenLastCalledWith({
      fromPhone: "+15550001001",
      body: "second",
      conversationId: "conv-1",
    });
  });

  it("shows a gateway-down state on a 502 problem response", async () => {
    vi.mocked(simulator.sendSimulatorMessage).mockRejectedValue(
      new ApiError(502, "service unavailable"),
    );
    renderSimulator();
    await waitFor(() => expect(simulator.getSimulatorThread).toHaveBeenCalledTimes(1));

    fireEvent.change(screen.getByLabelText("Simulated customer message"), {
      target: { value: "hi" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByText("service unavailable")).toBeInTheDocument();
  });

  it("polls the thread every 2s after an accepted send and stops on a new reply", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.mocked(simulator.sendSimulatorMessage).mockResolvedValue({
      conversationId: "conv-1",
      eventId: "evt-1",
      accepted: true,
    });
    renderSimulator();
    await waitFor(() => expect(simulator.getSimulatorThread).toHaveBeenCalledTimes(1));

    fireEvent.change(screen.getByLabelText("Simulated customer message"), {
      target: { value: "hi" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(simulator.sendSimulatorMessage).toHaveBeenCalledTimes(1));

    // First poll tick: still no reply.
    vi.mocked(simulator.getSimulatorThread).mockResolvedValue({ caseId: null, messages: [] });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2_000);
    });
    expect(simulator.getSimulatorThread).toHaveBeenCalledTimes(2);

    // Second poll tick: the agent's reply has landed -- polling should stop.
    vi.mocked(simulator.getSimulatorThread).mockResolvedValue({
      caseId: null,
      messages: [turn({ messageId: "reply", author: "hermes", body: "In stock" })],
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2_000);
    });
    expect(simulator.getSimulatorThread).toHaveBeenCalledTimes(3);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(simulator.getSimulatorThread).toHaveBeenCalledTimes(3);
  });

  it("selecting the verified preset fills the phone field with the seeded number and reloads the thread", async () => {
    renderSimulator();
    await waitFor(() => expect(simulator.getSimulatorThread).toHaveBeenCalledTimes(1));

    fireEvent.change(screen.getByLabelText("Identity preset"), {
      target: { value: "verified" },
    });

    expect(screen.getByLabelText("From phone")).toHaveValue("+14165550101");
    await waitFor(() =>
      expect(simulator.getSimulatorThread).toHaveBeenLastCalledWith("+14165550101"),
    );
  });

  it("selecting the unknown-caller preset fills a fresh +1555 number", async () => {
    renderSimulator();
    await waitFor(() => expect(simulator.getSimulatorThread).toHaveBeenCalledTimes(1));

    fireEvent.change(screen.getByLabelText("Identity preset"), {
      target: { value: "unknown" },
    });
    await waitFor(() => expect(simulator.getSimulatorThread).toHaveBeenCalledTimes(2));

    expect((screen.getByLabelText("From phone") as HTMLInputElement).value).toMatch(
      /^\+1555\d{7}$/,
    );
  });

  it("switching presets drops the prior conversationId so the next send starts fresh", async () => {
    vi.mocked(simulator.sendSimulatorMessage).mockResolvedValue({
      conversationId: "conv-1",
      eventId: "evt-1",
      accepted: true,
    });
    renderSimulator();
    await waitFor(() => expect(simulator.getSimulatorThread).toHaveBeenCalledTimes(1));

    fireEvent.change(screen.getByLabelText("Simulated customer message"), {
      target: { value: "first" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(simulator.sendSimulatorMessage).toHaveBeenCalledTimes(1));

    fireEvent.change(screen.getByLabelText("Identity preset"), {
      target: { value: "ambiguous" },
    });

    fireEvent.change(screen.getByLabelText("Simulated customer message"), {
      target: { value: "second" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() =>
      expect(simulator.sendSimulatorMessage).toHaveBeenLastCalledWith({
        fromPhone: "+14165550222",
        body: "second",
        conversationId: undefined,
      }),
    );
  });

  it("reset clears the thread view, the case link, and generates a fresh unknown number", async () => {
    vi.mocked(simulator.getSimulatorThread).mockResolvedValue({
      caseId: "case_1",
      messages: [turn({ messageId: "1", author: "customer", body: "hi there" })],
    });
    renderSimulator();
    expect(await screen.findByText("hi there")).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "Open case in copilot" })).toBeInTheDocument();

    vi.mocked(simulator.getSimulatorThread).mockResolvedValue({ caseId: null, messages: [] });
    fireEvent.click(screen.getByRole("button", { name: "Reset / new conversation" }));

    expect(screen.queryByText("hi there")).toBeNull();
    expect(screen.queryByRole("link", { name: "Open case in copilot" })).toBeNull();
    const phoneValue = (screen.getByLabelText("From phone") as HTMLInputElement).value;
    expect(phoneValue).toMatch(/^\+1555\d{7}$/);
    expect(phoneValue).not.toBe("+15550001001");
    await waitFor(() => expect(simulator.getSimulatorThread).toHaveBeenCalledTimes(2));
  });

  it("renders the FR-12 case link once the thread carries a caseId, not before", async () => {
    vi.mocked(simulator.getSimulatorThread).mockResolvedValue({ caseId: null, messages: [] });
    renderSimulator();
    await waitFor(() => expect(simulator.getSimulatorThread).toHaveBeenCalledTimes(1));
    expect(screen.queryByRole("link", { name: "Open case in copilot" })).toBeNull();

    vi.mocked(simulator.getSimulatorThread).mockResolvedValue({
      caseId: "case_1",
      messages: [],
    });
    fireEvent.blur(screen.getByLabelText("From phone"));

    const link = await screen.findByRole("link", { name: "Open case in copilot" });
    expect(link).toHaveAttribute("href", "/copilot?case=case_1");
  });

  it("an old-phone loadThread that resolves after Reset does not repaint the stale thread", async () => {
    const stale = deferred<simulator.SimulatorThreadResponse>();
    let call = 0;
    vi.mocked(simulator.getSimulatorThread).mockImplementation(() => {
      call += 1;
      if (call === 1) return Promise.resolve({ caseId: null, messages: [] }); // mount
      if (call === 2) return stale.promise; // onBlur reload for the OLD (still current) phone -- hangs
      return Promise.resolve({ caseId: null, messages: [] }); // Reset's reload for the NEW phone
    });
    renderSimulator();
    await waitFor(() => expect(simulator.getSimulatorThread).toHaveBeenCalledTimes(1));

    // Re-trigger a load for the still-current phone; this one hangs.
    fireEvent.blur(screen.getByLabelText("From phone"));
    await waitFor(() => expect(simulator.getSimulatorThread).toHaveBeenCalledTimes(2));

    // Reset switches to a new phone while call #2 is still in flight.
    fireEvent.click(screen.getByRole("button", { name: "Reset / new conversation" }));
    await waitFor(() => expect(simulator.getSimulatorThread).toHaveBeenCalledTimes(3));

    // Now the OLD phone's fetch resolves, carrying a thread that belongs to
    // the phone the user has since left.
    await act(async () => {
      stale.resolve({
        caseId: "case_stale",
        messages: [turn({ messageId: "stale", author: "customer", body: "stale message" })],
      });
      await stale.promise;
    });

    expect(screen.queryByText("stale message")).toBeNull();
    expect(screen.queryByRole("link", { name: "Open case in copilot" })).toBeNull();
  });

  it("a Reset during a pending send drops the stale response instead of restarting polling for the old phone", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const pendingSend = deferred<simulator.SimulatorSendResponse>();
    vi.mocked(simulator.sendSimulatorMessage).mockReturnValue(pendingSend.promise);
    renderSimulator();
    await waitFor(() => expect(simulator.getSimulatorThread).toHaveBeenCalledTimes(1));

    fireEvent.change(screen.getByLabelText("Simulated customer message"), {
      target: { value: "hi" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(simulator.sendSimulatorMessage).toHaveBeenCalledTimes(1));

    // Reset while the send for the OLD phone is still pending.
    fireEvent.click(screen.getByRole("button", { name: "Reset / new conversation" }));
    await waitFor(() => expect(simulator.getSimulatorThread).toHaveBeenCalledTimes(2));

    // The old phone's send now resolves accepted, as if the gateway had
    // answered late.
    await act(async () => {
      pendingSend.resolve({ conversationId: "conv-old", eventId: "evt-1", accepted: true });
      await pendingSend.promise;
    });

    // Had the stale response restarted polling for the old phone, advancing
    // past a poll tick would fire another thread fetch.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2_000);
    });
    expect(simulator.getSimulatorThread).toHaveBeenCalledTimes(2);

    // The next send (on the reset phone) must open a fresh conversation --
    // proving conversationId was never repopulated with "conv-old".
    vi.mocked(simulator.sendSimulatorMessage).mockResolvedValueOnce({
      conversationId: "conv-new",
      eventId: "evt-2",
      accepted: false,
    });
    fireEvent.change(screen.getByLabelText("Simulated customer message"), {
      target: { value: "second" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() =>
      expect(simulator.sendSimulatorMessage).toHaveBeenLastCalledWith(
        expect.objectContaining({ body: "second", conversationId: undefined }),
      ),
    );
  });

  // --- "link identity" control (0.0.3 S05, FR-13) ---------------------------

  it("clicking link identity calls the route with the current phone and shows the linked state", async () => {
    vi.mocked(simulator.linkSimulatorIdentity).mockResolvedValue({
      linked: true,
      channel: "sms",
      channelIdentity: "+15550001001",
      shopifyCustomerId: "gid://shopify/Customer/1001",
    });
    renderSimulator();
    await waitFor(() => expect(simulator.getSimulatorThread).toHaveBeenCalledTimes(1));

    fireEvent.click(
      screen.getByRole("button", { name: /Link identity to Acme Fleet/ }),
    );

    await waitFor(() =>
      expect(simulator.linkSimulatorIdentity).toHaveBeenCalledWith({
        channelIdentity: "+15550001001",
        shopifyCustomerId: "gid://shopify/Customer/1001",
        companyName: "Acme Fleet",
      }),
    );
    expect(await screen.findByText(/Linked to Acme Fleet/)).toBeInTheDocument();
  });

  it("links whichever phone is current after switching to a preset", async () => {
    vi.mocked(simulator.linkSimulatorIdentity).mockResolvedValue({
      linked: true,
      channel: "sms",
      channelIdentity: "+14165550222",
      shopifyCustomerId: "gid://shopify/Customer/1001",
    });
    renderSimulator();
    await waitFor(() => expect(simulator.getSimulatorThread).toHaveBeenCalledTimes(1));

    fireEvent.change(screen.getByLabelText("Identity preset"), {
      target: { value: "ambiguous" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: /Link identity to Acme Fleet/ }),
    );

    await waitFor(() =>
      expect(simulator.linkSimulatorIdentity).toHaveBeenCalledWith(
        expect.objectContaining({ channelIdentity: "+14165550222" }),
      ),
    );
  });

  it("shows a governed error message when the link is denied (e.g. not simulated mode)", async () => {
    vi.mocked(simulator.linkSimulatorIdentity).mockRejectedValue(
      new ApiError(403, "policy_blocked"),
    );
    renderSimulator();
    await waitFor(() => expect(simulator.getSimulatorThread).toHaveBeenCalledTimes(1));

    fireEvent.click(
      screen.getByRole("button", { name: /Link identity to Acme Fleet/ }),
    );

    expect(await screen.findByText("policy_blocked")).toBeInTheDocument();
  });

  it("resetting clears a prior linked status", async () => {
    vi.mocked(simulator.linkSimulatorIdentity).mockResolvedValue({
      linked: true,
      channel: "sms",
      channelIdentity: "+15550001001",
      shopifyCustomerId: "gid://shopify/Customer/1001",
    });
    renderSimulator();
    await waitFor(() => expect(simulator.getSimulatorThread).toHaveBeenCalledTimes(1));

    fireEvent.click(
      screen.getByRole("button", { name: /Link identity to Acme Fleet/ }),
    );
    expect(await screen.findByText(/Linked to Acme Fleet/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Reset / new conversation" }));
    expect(screen.queryByText(/Linked to Acme Fleet/)).toBeNull();
    await waitFor(() => expect(simulator.getSimulatorThread).toHaveBeenCalledTimes(2));
  });

  // --- SMS/email channel switcher (0.0.3 S18, FR-11) ------------------------

  it("defaults to SMS mode and never touches the email ingress or read-back", async () => {
    vi.mocked(simulator.sendSimulatorMessage).mockResolvedValue({
      conversationId: "conv-1",
      eventId: "evt-1",
      accepted: true,
    });
    renderSimulator();
    await waitFor(() => expect(simulator.getSimulatorThread).toHaveBeenCalledTimes(1));

    fireEvent.change(screen.getByLabelText("Simulated customer message"), {
      target: { value: "hi" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => expect(simulator.sendSimulatorMessage).toHaveBeenCalledTimes(1));
    expect(simulator.sendSimulatorEmail).not.toHaveBeenCalled();
    expect(simulator.getSimulatorEmailThread).not.toHaveBeenCalled();
  });

  it("switching to email mode swaps the identity field for a From-address + Subject composer", async () => {
    renderSimulator();
    await waitFor(() => expect(simulator.getSimulatorThread).toHaveBeenCalledTimes(1));
    expect(screen.getByLabelText("From phone")).toBeInTheDocument();
    expect(screen.queryByLabelText("From address")).toBeNull();

    vi.mocked(simulator.getSimulatorEmailThread).mockResolvedValue({ caseId: null, messages: [] });
    fireEvent.change(screen.getByLabelText("Channel"), { target: { value: "email" } });

    expect(screen.queryByLabelText("From phone")).toBeNull();
    expect(screen.getByLabelText("From address")).toBeInTheDocument();
    expect(screen.getByLabelText("Subject")).toBeInTheDocument();
    await waitFor(() => expect(simulator.getSimulatorEmailThread).toHaveBeenCalledTimes(1));
  });

  it("in email mode, submitting the composer posts {from, subject, body} to the email ingress", async () => {
    vi.mocked(simulator.getSimulatorEmailThread).mockResolvedValue({ caseId: null, messages: [] });
    vi.mocked(simulator.sendSimulatorEmail).mockResolvedValue({
      conversationId: "conv-em-1",
      eventId: "evt-em-1",
      accepted: true,
    });
    renderSimulator();
    await waitFor(() => expect(simulator.getSimulatorThread).toHaveBeenCalledTimes(1));

    fireEvent.change(screen.getByLabelText("Channel"), { target: { value: "email" } });
    await waitFor(() => expect(simulator.getSimulatorEmailThread).toHaveBeenCalledTimes(1));

    fireEvent.change(screen.getByLabelText("From address"), {
      target: { value: "accounts@acme-fleet.example" },
    });
    fireEvent.change(screen.getByLabelText("Subject"), { target: { value: "Order 10444" } });
    fireEvent.change(screen.getByLabelText("Simulated customer message"), {
      target: { value: "Where is my order?" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() =>
      expect(simulator.sendSimulatorEmail).toHaveBeenCalledWith({
        from: "accounts@acme-fleet.example",
        subject: "Order 10444",
        body: "Where is my order?",
        conversationId: undefined,
      }),
    );
    expect(simulator.sendSimulatorMessage).not.toHaveBeenCalled();
    expect(await screen.findByText(/Accepted/)).toBeInTheDocument();
  });

  it("switching from SMS to email resets the thread view instead of showing the stale SMS thread", async () => {
    vi.mocked(simulator.getSimulatorThread).mockResolvedValue({
      caseId: "case_sms",
      messages: [turn({ messageId: "1", author: "customer", body: "sms hello" })],
    });
    renderSimulator();
    expect(await screen.findByText("sms hello")).toBeInTheDocument();

    vi.mocked(simulator.getSimulatorEmailThread).mockResolvedValue({ caseId: null, messages: [] });
    fireEvent.change(screen.getByLabelText("Channel"), { target: { value: "email" } });

    await waitFor(() => expect(simulator.getSimulatorEmailThread).toHaveBeenCalledTimes(1));
    // Wait on the rendered outcome, not the fetch call: switchIdentity does not
    // clear the transcript synchronously -- it repaints when loadThread resolves.
    // Asserting right after the call only passed because the mock happened to
    // settle within waitFor's poll interval, which a loaded CI runner does not.
    await waitFor(() => expect(screen.queryByText("sms hello")).toBeNull());
  });

  it("selecting the verified email preset fills the From address field with the seeded address", async () => {
    renderSimulator();
    await waitFor(() => expect(simulator.getSimulatorThread).toHaveBeenCalledTimes(1));
    vi.mocked(simulator.getSimulatorEmailThread).mockResolvedValue({ caseId: null, messages: [] });
    fireEvent.change(screen.getByLabelText("Channel"), { target: { value: "email" } });
    await waitFor(() => expect(simulator.getSimulatorEmailThread).toHaveBeenCalledTimes(1));

    fireEvent.change(screen.getByLabelText("Identity preset"), {
      target: { value: "verified" },
    });

    expect(screen.getByLabelText("From address")).toHaveValue("accounts@acme-fleet.example");
    await waitFor(() =>
      expect(simulator.getSimulatorEmailThread).toHaveBeenLastCalledWith(
        "accounts@acme-fleet.example",
      ),
    );
  });

  it("reset in email mode clears the thread and generates a fresh simulated address", async () => {
    renderSimulator();
    await waitFor(() => expect(simulator.getSimulatorThread).toHaveBeenCalledTimes(1));
    vi.mocked(simulator.getSimulatorEmailThread).mockResolvedValue({
      caseId: "case_email",
      messages: [turn({ messageId: "1", author: "customer", body: "hi there" })],
    });
    fireEvent.change(screen.getByLabelText("Channel"), { target: { value: "email" } });
    expect(await screen.findByText("hi there")).toBeInTheDocument();

    vi.mocked(simulator.getSimulatorEmailThread).mockResolvedValue({ caseId: null, messages: [] });
    fireEvent.click(screen.getByRole("button", { name: "Reset / new conversation" }));

    expect(screen.queryByText("hi there")).toBeNull();
    const addressValue = (screen.getByLabelText("From address") as HTMLInputElement).value;
    expect(addressValue).toMatch(/^unknown-\d{7}@sim\.example$/);
    await waitFor(() => expect(simulator.getSimulatorEmailThread).toHaveBeenCalledTimes(2));
  });

  it("hides the SMS-only link-identity control in email mode (S05's link control is out of scope here)", async () => {
    renderSimulator();
    await waitFor(() => expect(simulator.getSimulatorThread).toHaveBeenCalledTimes(1));
    expect(
      screen.getByRole("button", { name: /Link identity to Acme Fleet/ }),
    ).toBeInTheDocument();

    vi.mocked(simulator.getSimulatorEmailThread).mockResolvedValue({ caseId: null, messages: [] });
    fireEvent.change(screen.getByLabelText("Channel"), { target: { value: "email" } });
    await waitFor(() => expect(simulator.getSimulatorEmailThread).toHaveBeenCalledTimes(1));

    expect(screen.queryByRole("button", { name: /Link identity to Acme Fleet/ })).toBeNull();
  });

  it("switching back to SMS from email restores the SMS composer and posts through the SMS route again", async () => {
    vi.mocked(simulator.sendSimulatorMessage).mockResolvedValue({
      conversationId: "conv-1",
      eventId: "evt-1",
      accepted: true,
    });
    renderSimulator();
    await waitFor(() => expect(simulator.getSimulatorThread).toHaveBeenCalledTimes(1));

    vi.mocked(simulator.getSimulatorEmailThread).mockResolvedValue({ caseId: null, messages: [] });
    fireEvent.change(screen.getByLabelText("Channel"), { target: { value: "email" } });
    await waitFor(() => expect(simulator.getSimulatorEmailThread).toHaveBeenCalledTimes(1));

    fireEvent.change(screen.getByLabelText("Channel"), { target: { value: "sms" } });
    await waitFor(() => expect(simulator.getSimulatorThread).toHaveBeenCalledTimes(2));

    fireEvent.change(screen.getByLabelText("Simulated customer message"), {
      target: { value: "back on sms" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() =>
      expect(simulator.sendSimulatorMessage).toHaveBeenCalledWith({
        fromPhone: "+15550001001",
        body: "back on sms",
        conversationId: undefined,
      }),
    );
  });
});
