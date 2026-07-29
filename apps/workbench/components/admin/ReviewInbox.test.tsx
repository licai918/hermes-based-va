import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { InboxItem } from "@/lib/bff/admin/review-inbox";
import { ReviewInbox, ReviewInboxView } from "./ReviewInbox";

const NOW = 1_700_000_000_000;

function item(overrides: Partial<InboxItem> = {}): InboxItem {
  return {
    kind: "l6_proposal",
    layer: "L6",
    id: "aexp_1",
    subject: "reps confirm 2055516 means the tire size",
    detail: "note",
    createdAt: NOW,
    annotations: null,
    decisions: ["accept", "reject"],
    reclassifiable: true,
    ...overrides,
  };
}

function baseProps(items: InboxItem[] = [item()]) {
  return {
    items,
    count: items.length,
    loading: false,
    error: null as string | null,
    busyId: null as string | null,
    rowErrors: {} as Record<string, string>,
    rowNotices: {} as Record<string, string>,
    reclassifyId: null as string | null,
    onDecide: vi.fn(),
    onAnnotate: vi.fn(),
    onOpenReclassify: vi.fn(),
    onReclassify: vi.fn(),
  };
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

describe("ReviewInboxView", () => {
  it("renders one queue with the layer badge only where the kind determines it", () => {
    render(
      <ReviewInboxView
        {...baseProps([
          item(),
          item({
            kind: "l7_proposal",
            layer: "L7",
            id: "lex_1",
            subject: "2055516 → 205/55R16",
          }),
          item({
            kind: "graduation",
            layer: null,
            id: "rvw_1",
            subject: "aexp_9",
            decisions: ["acknowledge", "dismiss"],
            reclassifiable: false,
          }),
        ])}
      />,
    );

    // Every kind is present as a badge -- this is ONE queue, not three lists.
    expect(screen.getByText("l6_proposal")).toBeTruthy();
    expect(screen.getByText("l7_proposal")).toBeTruthy();
    expect(screen.getByText("graduation")).toBeTruthy();
    expect(screen.getByText("L6")).toBeTruthy();
    expect(screen.getByText("L7")).toBeTruthy();
    // The graduation row carries no layer claim: its emitting slice (S20) has
    // not landed and a guessed badge on a governance surface would be a lie.
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });

  it("offers each kind exactly the decisions its own layer can honour", () => {
    const onDecide = vi.fn();
    render(
      <ReviewInboxView
        {...baseProps([
          item(),
          item({
            kind: "blast_radius",
            layer: null,
            id: "rvw_1",
            subject: "mem_9",
            decisions: ["acknowledge", "dismiss"],
            reclassifiable: false,
          }),
        ])}
        onDecide={onDecide}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Accept aexp_1" }));
    expect(onDecide).toHaveBeenCalledWith(
      expect.objectContaining({ id: "aexp_1" }),
      "accept",
    );
    fireEvent.click(screen.getByRole("button", { name: "Dismiss rvw_1" }));
    expect(onDecide).toHaveBeenCalledWith(
      expect.objectContaining({ id: "rvw_1" }),
      "dismiss",
    );

    // The negative half, and it is the discriminating half: an Accept on a
    // blast-radius item would have to invent a decision primitive, and only a
    // mis-filed PROPOSAL can be re-classified.
    expect(screen.queryByRole("button", { name: "Accept rvw_1" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Acknowledge aexp_1" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Re-classify rvw_1" })).toBeNull();
    expect(screen.getByRole("button", { name: "Re-classify aexp_1" })).toBeTruthy();
  });

  it("renders S13 and S16 annotations as distinct labelled blocks", () => {
    // D8: two reserved keys on ONE column. They must not read as one blob --
    // "a heuristic guessed this" and "the copilot triaged this" are different
    // claims with different weight.
    render(
      <ReviewInboxView
        {...baseProps([
          item({
            annotations: {
              heuristic: "looks like a lexicon entry",
              copilot: "duplicate of aexp_4",
            },
          }),
        ])}
      />,
    );
    expect(screen.getByTestId("annotation-heuristic").textContent).toContain(
      "Advisory",
    );
    expect(screen.getByTestId("annotation-heuristic").textContent).toContain(
      "looks like a lexicon entry",
    );
    expect(screen.getByTestId("annotation-copilot").textContent).toContain("Triage");
    expect(screen.getByTestId("annotation-copilot").textContent).toContain(
      "duplicate of aexp_4",
    );
  });

  it("shows no annotation block on a row that has none", () => {
    render(<ReviewInboxView {...baseProps([item()])} />);
    expect(screen.queryByTestId("annotation-heuristic")).toBeNull();
  });

  it("submits a re-classification with the target the admin typed", () => {
    const onReclassify = vi.fn();
    render(
      <ReviewInboxView
        {...baseProps()}
        reclassifyId="aexp_1"
        onReclassify={onReclassify}
      />,
    );

    fireEvent.change(screen.getByLabelText("Domain"), {
      target: { value: "tire" },
    });
    fireEvent.change(screen.getByLabelText("Surface form"), {
      target: { value: "2055516" },
    });
    fireEvent.change(screen.getByLabelText("Canonical form"), {
      target: { value: "205/55R16" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Move to lexicon queue" }));

    expect(onReclassify).toHaveBeenCalledWith(
      expect.objectContaining({ id: "aexp_1" }),
      {
        domain: "tire",
        entryKind: "alias",
        surfaceForm: "2055516",
        canonicalForm: "205/55R16",
      },
    );
  });

  it("renders the badge count and an empty queue honestly", () => {
    const { rerender } = render(<ReviewInboxView {...baseProps()} />);
    expect(screen.getByTestId("inbox-count").textContent).toBe("1");

    rerender(<ReviewInboxView {...baseProps([])} />);
    expect(screen.getByTestId("inbox-count").textContent).toBe("0");
    expect(screen.getByText("Nothing waiting for review.")).toBeTruthy();
  });

  it("keeps a failed row actionable with its error inline", () => {
    render(
      <ReviewInboxView {...baseProps()} rowErrors={{ aexp_1: "policy blocked" }} />,
    );
    expect(screen.getByRole("alert").textContent).toContain("policy blocked");
    // Still clickable: a failed decision must be retryable, not a dead row.
    expect(
      (screen.getByRole("button", { name: "Accept aexp_1" }) as HTMLButtonElement)
        .disabled,
    ).toBe(false);
  });
});

describe("ReviewInbox (container)", () => {
  it("re-reads the queue after a decision, so the badge and the list agree", async () => {
    const calls: { url: string; method: string; body: unknown }[] = [];
    let listCall = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? "GET";
        calls.push({
          url,
          method,
          body: init?.body ? JSON.parse(init.body as string) : null,
        });
        if (method === "GET") {
          listCall += 1;
          return listCall === 1
            ? jsonResponse({ items: [item()], count: 1 })
            : jsonResponse({ items: [], count: 0 });
        }
        return jsonResponse({ kind: "l6_proposal", id: "aexp_1", result: {} });
      }),
    );

    render(<ReviewInbox />);
    await screen.findByRole("button", { name: "Accept aexp_1" });

    fireEvent.click(screen.getByRole("button", { name: "Accept aexp_1" }));

    await waitFor(() =>
      expect(screen.getByText("Nothing waiting for review.")).toBeTruthy(),
    );
    expect(screen.getByTestId("inbox-count").textContent).toBe("0");
    // The decision carried the KIND, which is what routes it to the right
    // governed action -- an id alone is ambiguous across the three stores.
    expect(calls.find((c) => c.method === "POST")).toEqual({
      url: "/api/admin/inbox/decide",
      method: "POST",
      body: { kind: "l6_proposal", id: "aexp_1", decision: "accept" },
    });
    vi.unstubAllGlobals();
  });

  // --- 0.0.5 S16 (FR-23): the on-demand re-triage button -------------------

  it("re-reads the queue after a re-triage, so the new note is on the row", async () => {
    const calls: { url: string; method: string; body: unknown }[] = [];
    let listCall = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? "GET";
        calls.push({
          url,
          method,
          body: init?.body ? JSON.parse(init.body as string) : null,
        });
        if (method === "GET") {
          listCall += 1;
          return listCall === 1
            ? jsonResponse({ items: [item()], count: 1 })
            : jsonResponse({
                items: [
                  item({
                    annotations: { copilot: { recommendation: "reject" } },
                  }),
                ],
                count: 1,
              });
        }
        return jsonResponse({
          kind: "l6_proposal",
          id: "aexp_1",
          annotated: true,
          annotation: { recommendation: "reject" },
          reason: null,
        });
      }),
    );

    render(<ReviewInbox />);
    await screen.findByRole("button", { name: "Re-triage aexp_1" });
    fireEvent.click(screen.getByRole("button", { name: "Re-triage aexp_1" }));

    // The ROW stays -- an annotation is not a decision, so unlike Accept this
    // must not empty the queue -- and the fresh note is now rendered on it.
    await waitFor(() =>
      expect(screen.getByTestId("annotation-copilot")).toBeTruthy(),
    );
    expect(screen.getByTestId("inbox-count").textContent).toBe("1");
    expect(calls.find((c) => c.method === "POST")).toEqual({
      url: "/api/admin/inbox/annotate",
      method: "POST",
      body: { kind: "l6_proposal", id: "aexp_1" },
    });
    vi.unstubAllGlobals();
  });

  it("reports a disabled annotator as a notice, not as an error", async () => {
    // FR-23 is default-OFF, so "nothing was annotated" is the SHIPPED state, not
    // a fault. Rendering it in the error channel would send an admin hunting a
    // failure that is a configuration -- and would hide a real one among them.
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: string, init?: RequestInit) => {
        if ((init?.method ?? "GET") === "GET") {
          return jsonResponse({ items: [item()], count: 1 });
        }
        return jsonResponse({
          kind: "l6_proposal",
          id: "aexp_1",
          annotated: false,
          annotation: null,
          reason: "copilot triage annotations are off for this deployment",
        });
      }),
    );

    render(<ReviewInbox />);
    await screen.findByRole("button", { name: "Re-triage aexp_1" });
    fireEvent.click(screen.getByRole("button", { name: "Re-triage aexp_1" }));

    await waitFor(() =>
      expect(screen.getByTestId("notice-aexp_1").textContent).toContain(
        "off for this deployment",
      ),
    );
    expect(screen.queryByRole("alert")).toBeNull();
    vi.unstubAllGlobals();
  });
});
