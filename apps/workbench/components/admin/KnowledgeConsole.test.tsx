import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { PolicySlot } from "@/lib/bff/admin/knowledge";
import { ErrorBannerProvider } from "@/components/shell/error-banner";
import { KnowledgeConsole, KnowledgeConsoleView } from "./KnowledgeConsole";

function slot(overrides: Partial<PolicySlot> & Pick<PolicySlot, "slotId" | "title">): PolicySlot {
  return {
    status: "empty",
    draftText: null,
    publishedText: null,
    owner: null,
    reviewDate: null,
    hasGapPrompt: false,
    ...overrides,
  };
}

const SLOTS: PolicySlot[] = [
  slot({
    slotId: "business-hours",
    title: "Business hours and service boundaries",
    status: "published",
    publishedText: "Open Mon-Fri 8am-6pm.",
    owner: "ops-lead",
    reviewDate: "2026-09-01",
  }),
  slot({
    slotId: "order-delivery",
    title: "Order and delivery inquiry guidance",
    status: "draft",
    draftText: "Confirm order number, then share status.",
  }),
  slot({
    slotId: "exception-scripts",
    title: "Standard exception scripts",
    status: "gap",
    hasGapPrompt: true,
  }),
];

const EMPTY_EDITOR = { draftText: "", owner: "", reviewDate: "" };

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

describe("KnowledgeConsoleView", () => {
  it("renders all slots with their status badges", () => {
    render(
      <KnowledgeConsoleView
        slots={SLOTS}
        selectedId={null}
        editor={EMPTY_EDITOR}
        busy={false}
        error={null}
        onSelect={() => {}}
        onEditorChange={() => {}}
        onSave={() => {}}
        onSubmit={() => {}}
        onRollback={() => {}}
      />,
    );
    expect(screen.getByRole("button", { name: /Business hours/ })).toBeInTheDocument();
    expect(screen.getByText("Published")).toBeInTheDocument();
    expect(screen.getByText("Draft")).toBeInTheDocument();
    expect(screen.getByText("Gap")).toBeInTheDocument();
  });

  it("prompts to pick a slot when none is selected", () => {
    render(
      <KnowledgeConsoleView
        slots={SLOTS}
        selectedId={null}
        editor={EMPTY_EDITOR}
        busy={false}
        error={null}
        onSelect={() => {}}
        onEditorChange={() => {}}
        onSave={() => {}}
        onSubmit={() => {}}
        onRollback={() => {}}
      />,
    );
    expect(screen.getByText(/select a policy slot/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/draft text/i)).not.toBeInTheDocument();
  });

  it("shows the editor for the selected slot", () => {
    render(
      <KnowledgeConsoleView
        slots={SLOTS}
        selectedId="order-delivery"
        editor={{ draftText: "Confirm order number, then share status.", owner: "", reviewDate: "" }}
        busy={false}
        error={null}
        onSelect={() => {}}
        onEditorChange={() => {}}
        onSave={() => {}}
        onSubmit={() => {}}
        onRollback={() => {}}
      />,
    );
    expect(screen.getByRole("heading", { name: /Order and delivery/ })).toBeInTheDocument();
    expect(screen.getByLabelText(/draft text/i)).toHaveValue(
      "Confirm order number, then share status.",
    );
  });

  it("enables Submit only for a draft slot and hides Rollback", () => {
    render(
      <KnowledgeConsoleView
        slots={SLOTS}
        selectedId="order-delivery"
        editor={EMPTY_EDITOR}
        busy={false}
        error={null}
        onSelect={() => {}}
        onEditorChange={() => {}}
        onSave={() => {}}
        onSubmit={() => {}}
        onRollback={() => {}}
      />,
    );
    expect(screen.getByRole("button", { name: /submit for eval/i })).toBeEnabled();
    expect(screen.queryByRole("button", { name: /rollback/i })).not.toBeInTheDocument();
  });

  it("disables Submit and shows Rollback for a published slot", () => {
    render(
      <KnowledgeConsoleView
        slots={SLOTS}
        selectedId="business-hours"
        editor={EMPTY_EDITOR}
        busy={false}
        error={null}
        onSelect={() => {}}
        onEditorChange={() => {}}
        onSave={() => {}}
        onSubmit={() => {}}
        onRollback={() => {}}
      />,
    );
    expect(screen.getByRole("button", { name: /submit for eval/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /rollback/i })).toBeEnabled();
  });

  it("shows gap guidance for a gap slot", () => {
    render(
      <KnowledgeConsoleView
        slots={SLOTS}
        selectedId="exception-scripts"
        editor={EMPTY_EDITOR}
        busy={false}
        error={null}
        onSelect={() => {}}
        onEditorChange={() => {}}
        onSave={() => {}}
        onSubmit={() => {}}
        onRollback={() => {}}
      />,
    );
    expect(screen.getByText(/no policy captured yet/i)).toBeInTheDocument();
  });

  it("wires the row, editor, and action callbacks", () => {
    const onSelect = vi.fn();
    const onEditorChange = vi.fn();
    const onSave = vi.fn();
    const onSubmit = vi.fn();
    render(
      <KnowledgeConsoleView
        slots={SLOTS}
        selectedId="order-delivery"
        editor={EMPTY_EDITOR}
        busy={false}
        error={null}
        onSelect={onSelect}
        onEditorChange={onEditorChange}
        onSave={onSave}
        onSubmit={onSubmit}
        onRollback={() => {}}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /Business hours/ }));
    expect(onSelect).toHaveBeenCalledWith("business-hours");

    fireEvent.change(screen.getByLabelText(/owner/i), { target: { value: "casey" } });
    expect(onEditorChange).toHaveBeenCalledWith({ owner: "casey" });

    fireEvent.click(screen.getByRole("button", { name: /save draft/i }));
    expect(onSave).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: /submit for eval/i }));
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it("renders an inline alert when given an error", () => {
    render(
      <KnowledgeConsoleView
        slots={SLOTS}
        selectedId="order-delivery"
        editor={EMPTY_EDITOR}
        busy={false}
        error="slot has no draft to submit"
        onSelect={() => {}}
        onEditorChange={() => {}}
        onSave={() => {}}
        onSubmit={() => {}}
        onRollback={() => {}}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent(/no draft to submit/i);
  });
});

describe("KnowledgeConsole (fetching container)", () => {
  afterEach(() => vi.unstubAllGlobals());

  function renderConsole() {
    return render(
      <ErrorBannerProvider>
        <KnowledgeConsole />
      </ErrorBannerProvider>,
    );
  }

  it("loads slots on mount", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ slots: SLOTS })),
    );
    renderConsole();
    expect(await screen.findByRole("button", { name: /Business hours/ })).toBeInTheDocument();
    expect(screen.getByText("Gap")).toBeInTheDocument();
  });

  it("selecting a slot reveals its editor", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ slots: SLOTS })),
    );
    renderConsole();
    fireEvent.click(await screen.findByRole("button", { name: /Order and delivery/ }));
    expect(screen.getByLabelText(/draft text/i)).toHaveValue(
      "Confirm order number, then share status.",
    );
  });

  it("Save draft PUTs the edited fields then refetches", async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      if (method === "PUT") return Promise.resolve(jsonResponse({ slot: SLOTS[1] }));
      return Promise.resolve(jsonResponse({ slots: SLOTS }));
    });
    vi.stubGlobal("fetch", fetchMock);
    renderConsole();

    fireEvent.click(await screen.findByRole("button", { name: /Order and delivery/ }));
    fireEvent.change(screen.getByLabelText(/draft text/i), {
      target: { value: "Updated guidance" },
    });
    fireEvent.change(screen.getByLabelText(/owner/i), { target: { value: "casey" } });
    fireEvent.change(screen.getByLabelText(/review date/i), {
      target: { value: "2026-10-01" },
    });
    fireEvent.click(screen.getByRole("button", { name: /save draft/i }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith("/api/admin/knowledge/slots/order-delivery", {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          draftText: "Updated guidance",
          owner: "casey",
          reviewDate: "2026-10-01",
        }),
      }),
    );
    const slotsGets = fetchMock.mock.calls.filter(
      ([url, init]) => url === "/api/admin/knowledge/slots" && (init?.method ?? "GET") === "GET",
    );
    expect(slotsGets.length).toBeGreaterThanOrEqual(2);
  });

  it("surfaces a 409 from Submit as a visible alert", async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      if (typeof url === "string" && url.endsWith("/submit") && method === "POST") {
        return Promise.resolve(jsonResponse({ error: "slot has no draft to submit" }, 409));
      }
      return Promise.resolve(jsonResponse({ slots: SLOTS }));
    });
    vi.stubGlobal("fetch", fetchMock);
    renderConsole();

    fireEvent.click(await screen.findByRole("button", { name: /Order and delivery/ }));
    fireEvent.click(screen.getByRole("button", { name: /submit for eval/i }));

    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText(/no draft to submit/i)).toBeInTheDocument();
  });
});
