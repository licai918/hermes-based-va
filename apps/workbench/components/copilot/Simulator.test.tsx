import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ApiError } from "@/lib/api/http";
import type { ThreadMessage } from "@/lib/gateway/types";
import { ErrorBannerProvider } from "@/components/shell/error-banner";
import * as simulator from "@/lib/api/simulator-client";
import { Simulator } from "./Simulator";

vi.mock("@/lib/api/simulator-client", () => ({
  sendSimulatorMessage: vi.fn(),
  getSimulatorThread: vi.fn(),
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
});
