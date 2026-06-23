import { render, screen, within } from "@testing-library/react";
import type {
  AutoHandledRecord,
  ThreadMessage,
  ToolCallEvidence,
} from "@/lib/gateway/types";
import { AutoHandledDetail } from "./AutoHandledDetail";

function msg(over: Partial<ThreadMessage>): ThreadMessage {
  return {
    messageId: "m1",
    threadId: "t1",
    at: Date.now() - 10 * 60_000,
    author: "customer",
    channel: "sms",
    body: "Where is my order?",
    autoHandled: false,
    activeCaseSegment: false,
    ...over,
  };
}

function tool(over: Partial<ToolCallEvidence>): ToolCallEvidence {
  return {
    tool: "shopify",
    action: "order_status",
    inputSummary: "order #1001",
    outputSummary: "shipped",
    ...over,
  };
}

const RECORD: AutoHandledRecord = {
  recordId: "rec-1",
  channel: "sms",
  identitySummary: "Verified: Jane Doe",
  lastMessagePreview: "Thanks!",
  lastActivityAt: Date.now() - 5 * 60_000,
  outcome: "Auto-resolved",
  toolSummary: "order_status lookup",
  toolFailure: true,
  timeline: [
    msg({ messageId: "m1", author: "customer", body: "Where is my order?" }),
    msg({ messageId: "m2", author: "hermes", body: "It shipped yesterday.", autoHandled: true }),
  ],
  toolCalls: [
    tool({ tool: "shopify", action: "order_status", inputSummary: "order #1001", outputSummary: "shipped" }),
    tool({
      tool: "easyroutes",
      action: "track",
      inputSummary: "stop 5",
      outputSummary: "n/a",
      errorClass: "UnavailableSystemError",
    }),
  ],
};

function stubFetch(body: unknown, status = 200) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status })),
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("AutoHandledDetail", () => {
  it("renders the summary header, timeline and tool-call evidence", async () => {
    stubFetch({ record: RECORD });
    render(<AutoHandledDetail recordId="rec-1" />);

    expect(await screen.findByText("Verified: Jane Doe")).toBeInTheDocument();
    expect(screen.getByText("SMS")).toBeInTheDocument();
    expect(screen.getByText("Auto-resolved")).toBeInTheDocument();
    expect(screen.getByText(/tool failure/i)).toBeInTheDocument();

    expect(screen.getByText("Where is my order?")).toBeInTheDocument();
    expect(screen.getByText("It shipped yesterday.")).toBeInTheDocument();
    expect(screen.getByText("Customer")).toBeInTheDocument();
    expect(screen.getByText("Hermes")).toBeInTheDocument();

    const autoTurn = screen
      .getByText("It shipped yesterday.")
      .closest("li") as HTMLElement;
    expect(within(autoTurn).getByText(/auto-handled/i)).toBeInTheDocument();
    const humanTurn = screen
      .getByText("Where is my order?")
      .closest("li") as HTMLElement;
    expect(within(humanTurn).queryByText(/auto-handled/i)).toBeNull();

    expect(screen.getByText("shopify.order_status")).toBeInTheDocument();
    expect(screen.getByText("easyroutes.track")).toBeInTheDocument();
    expect(screen.getByText(/order #1001/)).toBeInTheDocument();
    expect(screen.getByText(/UnavailableSystemError/)).toBeInTheDocument();
  });

  it("shows a friendly not-found state on 404", async () => {
    stubFetch({ error: "record not found" }, 404);
    render(<AutoHandledDetail recordId="missing" />);
    expect(await screen.findByText(/not found/i)).toBeInTheDocument();
    expect(screen.queryByText("Verified: Jane Doe")).toBeNull();
  });
});
