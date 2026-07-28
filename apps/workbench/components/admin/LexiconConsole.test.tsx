import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { LexiconEntry } from "@/lib/gateway/types";
import { LexiconConsole, LexiconConsoleView } from "./LexiconConsole";

const NOW = 1_700_000_000_000;

function entry(overrides: Partial<LexiconEntry> = {}): LexiconEntry {
  return {
    id: "lex_1",
    domain: "company",
    entryKind: "alias",
    surfaceForm: "TOEE",
    canonicalForm: "TOEE TIRE",
    status: "proposed",
    provenance: "conversation_confirmed",
    evidence: null,
    proposerContext: null,
    piiRedacted: false,
    deciderAccountId: null,
    provenanceUnattributed: false,
    decidedAt: null,
    hitCount: 0,
    createdAt: NOW,
    updatedAt: NOW,
    ...overrides,
  };
}

function baseProps(entries: LexiconEntry[] = [entry()]) {
  return {
    entries,
    loading: false,
    error: null as string | null,
    busyId: null as string | null,
    rowErrors: {} as Record<string, string>,
    addError: null as string | null,
    statusFilter: "all" as const,
    onStatusFilter: vi.fn(),
    onDecide: vi.fn(),
    onEdit: vi.fn(),
    onAdd: vi.fn(),
  };
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

describe("LexiconConsoleView", () => {
  it("offers Approve/Reject on a proposed entry and Retire on a confirmed one", () => {
    const onDecide = vi.fn();
    render(
      <LexiconConsoleView
        {...baseProps([
          entry(),
          entry({ id: "lex_2", surfaceForm: "2055516", status: "confirmed" }),
        ])}
        onDecide={onDecide}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Approve TOEE" }));
    expect(onDecide).toHaveBeenCalledWith(expect.objectContaining({ id: "lex_1" }), "confirm");

    fireEvent.click(screen.getByRole("button", { name: "Retire 2055516" }));
    expect(onDecide).toHaveBeenCalledWith(expect.objectContaining({ id: "lex_2" }), "retire");

    // Retire is not an option on a proposal, and Approve is not one on a
    // confirmed entry: the transitions the store allows are the ones offered.
    expect(screen.queryByRole("button", { name: "Retire TOEE" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Approve 2055516" })).toBeNull();
  });

  it("offers no actions on a terminal entry", () => {
    render(<LexiconConsoleView {...baseProps([entry({ status: "retired" })])} />);
    expect(screen.queryByRole("button", { name: /TOEE/ })).toBeNull();
  });

  it("edits the canonical form in place and calls onEdit with the new value", () => {
    const onEdit = vi.fn();
    render(<LexiconConsoleView {...baseProps()} onEdit={onEdit} />);

    fireEvent.click(screen.getByRole("button", { name: "Edit TOEE" }));
    fireEvent.change(screen.getByLabelText("Canonical form for TOEE"), {
      target: { value: "TOEE TIRE LTD" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save TOEE" }));

    expect(onEdit).toHaveBeenCalledWith(
      expect.objectContaining({ id: "lex_1" }),
      "TOEE TIRE LTD",
    );
  });

  it("badges an unattributed admin_manual row (D20) and leaves an attributed one alone", () => {
    render(
      <LexiconConsoleView
        {...baseProps([
          entry({ provenance: "admin_manual", provenanceUnattributed: true }),
          entry({
            id: "lex_2",
            surfaceForm: "2055516",
            provenance: "admin_manual",
            deciderAccountId: "seed-admin",
            provenanceUnattributed: false,
          }),
        ])}
      />,
    );
    expect(screen.getAllByText("UNATTRIBUTED")).toHaveLength(1);
    expect(screen.getByText("seed-admin")).toBeInTheDocument();
  });

  it("never presents pii_redacted=false as a clean bill of health", () => {
    render(
      <LexiconConsoleView
        {...baseProps([
          entry({ piiRedacted: false }),
          entry({ id: "lex_2", surfaceForm: "2055516", piiRedacted: true }),
        ])}
      />,
    );
    // The false case says what happened -- no span was removed -- and the
    // footnote says why that is not the same as "no PII on this row" (D2's keep
    // exemption, recorded only in the audit log).
    expect(screen.getByText("None removed")).toBeInTheDocument();
    expect(screen.getByText("Scrubbed")).toBeInTheDocument();
    expect(screen.getByText(/not a statement that the row is free of PII/i)).toBeInTheDocument();
  });

  it("renders a per-row error without blanking the console", () => {
    render(
      <LexiconConsoleView {...baseProps()} rowErrors={{ lex_1: "conflict: already exists" }} />,
    );
    expect(screen.getByText("conflict: already exists")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve TOEE" })).toBeInTheDocument();
  });

  it("submits the add form with the four core fields", () => {
    const onAdd = vi.fn();
    render(<LexiconConsoleView {...baseProps()} onAdd={onAdd} />);

    fireEvent.change(screen.getByLabelText("Domain"), { target: { value: "company" } });
    fireEvent.change(screen.getByLabelText("Surface form"), { target: { value: "TOEE" } });
    fireEvent.change(screen.getByLabelText("Canonical form"), {
      target: { value: "TOEE TIRE" },
    });
    fireEvent.click(screen.getByRole("button", { name: /add entry/i }));

    expect(onAdd).toHaveBeenCalledWith({
      domain: "company",
      entryKind: "alias",
      surfaceForm: "TOEE",
      canonicalForm: "TOEE TIRE",
    });
  });
});

describe("LexiconConsole (fetching container)", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("loads on mount and re-reads through the ONE action when the filter changes", async () => {
    const fetchMock = vi.fn(() =>
      Promise.resolve(jsonResponse({ entries: [entry()], confirmedSetVersion: null })),
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<LexiconConsole />);
    expect(await screen.findByText("TOEE TIRE")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/api/admin/lexicon", expect.anything());

    fireEvent.change(screen.getByLabelText("Status"), { target: { value: "proposed" } });
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/admin/lexicon?status=proposed",
        expect.anything(),
      ),
    );
  });

  it("POSTs an approval and replaces the row with the governed response", async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if ((init?.method ?? "GET") === "POST") {
        return Promise.resolve(
          jsonResponse({
            entry: entry({ status: "confirmed", deciderAccountId: "seed-supervisor" }),
          }),
        );
      }
      return Promise.resolve(jsonResponse({ entries: [entry()] }));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<LexiconConsole />);
    fireEvent.click(await screen.findByRole("button", { name: "Approve TOEE" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/admin/lexicon/lex_1/confirm",
        expect.objectContaining({ method: "POST" }),
      ),
    );
    // The decided entry stays in the list showing its new status + decider --
    // never removed. Asserted through the row's controls and its decider cell:
    // the bare text "confirmed" also appears in the status filter's options, so
    // matching on it would prove nothing about the row.
    expect(await screen.findByRole("button", { name: "Retire TOEE" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve TOEE" })).toBeNull();
    expect(screen.getByText("seed-supervisor")).toBeInTheDocument();
  });

  it("PATCHes an edit to the same entry id (D7: in-place, never delete+create)", async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if ((init?.method ?? "GET") === "PATCH") {
        return Promise.resolve(
          jsonResponse({ entry: entry({ canonicalForm: "TOEE TIRE LTD", hitCount: 42 }) }),
        );
      }
      return Promise.resolve(jsonResponse({ entries: [entry({ hitCount: 42 })] }));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<LexiconConsole />);
    fireEvent.click(await screen.findByRole("button", { name: "Edit TOEE" }));
    fireEvent.change(screen.getByLabelText("Canonical form for TOEE"), {
      target: { value: "TOEE TIRE LTD" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save TOEE" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith("/api/admin/lexicon/lex_1", {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ canonicalForm: "TOEE TIRE LTD" }),
      }),
    );
    expect(await screen.findByText("TOEE TIRE LTD")).toBeInTheDocument();
    expect(screen.getByText("42")).toBeInTheDocument();
  });

  it("shows a governed add failure inline and keeps the form usable", async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/admin/lexicon" && (init?.method ?? "GET") === "POST") {
        return Promise.resolve(
          jsonResponse({ error: "semantic_lexicon already has an entry" }, 409),
        );
      }
      return Promise.resolve(jsonResponse({ entries: [entry()] }));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<LexiconConsole />);
    await screen.findByText("TOEE TIRE");

    fireEvent.change(screen.getByLabelText("Domain"), { target: { value: "company" } });
    fireEvent.change(screen.getByLabelText("Surface form"), { target: { value: "TOEE" } });
    fireEvent.change(screen.getByLabelText("Canonical form"), {
      target: { value: "TOEE TIRE" },
    });
    fireEvent.click(screen.getByRole("button", { name: /add entry/i }));

    expect(await screen.findByText(/already has an entry/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /add entry/i })).toBeEnabled();
  });
});
