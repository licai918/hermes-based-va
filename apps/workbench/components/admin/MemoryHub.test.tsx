// Memory Hub page (0.0.5 S14, FR-21/US9). The one property worth testing here
// beyond "it renders": a number never appears without the label that scopes it.
// Every assertion below finds the LABEL first and then reads the value out of the
// same element, so a renderer that drops the caption and shows a bare "5" fails.
import { render, screen } from "@testing-library/react";
import { MemoryHub } from "./MemoryHub";

const VIEW = {
  rows: [
    {
      layer: "L1",
      name: "Identity Graph",
      holds: "channel identities",
      status: "shipped",
      href: null,
      counts: [],
      note: "No live count on this hub and no console of its own.",
    },
    {
      layer: "L2",
      name: "Conversation",
      holds: "threads and turns",
      status: "shipped",
      href: "/copilot",
      counts: [],
      note: "No live count on this hub.",
    },
    {
      layer: "L3",
      name: "Operational",
      holds: "cases and audit",
      status: "shipped",
      href: "/copilot/audit/auto-handled",
      counts: [],
      note: "No live count on this hub.",
    },
    {
      layer: "L4",
      name: "Customer Memory",
      holds: "4 governed preference slots per customer",
      status: "shipped",
      href: "/admin/memory-audit",
      counts: [
        { label: "Customer bindings with at least one slot", value: "16" },
        { label: "Last retention sweep (UTC)", value: "2026-07-20T03:00:00.000Z" },
      ],
      note: "Counts only. L4 is the per-customer PII layer by design (NFR-6).",
    },
    {
      layer: "L5",
      name: "Knowledge",
      holds: "shared corpus",
      status: "shipped",
      href: "/admin/knowledge",
      counts: [{ label: "Corpus chunks", value: "167" }],
      note: null,
    },
    {
      layer: "L6",
      name: "Agent experience",
      holds: "operational learnings",
      status: "shipped",
      href: "/admin/agent-experience",
      counts: [
        { label: "Pending proposals (status = proposed)", value: "4" },
        { label: "Confirmed entries in the store — NOT what a turn carries", value: "2" },
      ],
      note: null,
    },
    {
      layer: "L7",
      name: "Semantic lexicon",
      holds: "domain language",
      status: "shipped",
      href: "/admin/lexicon",
      counts: [
        { label: "Pending proposals awaiting a decision", value: "3" },
        { label: "Confirmed in the store — the prompt glossary is bounded", value: "5" },
        { label: "Zero-hit confirmed entries — lifetime hit_count = 0", value: "2" },
      ],
      note: null,
    },
  ],
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

describe("MemoryHub", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("renders a row per layer L1-L7 and deep-links the ones that have a console", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(VIEW)));
    render(<MemoryHub />);

    for (const row of VIEW.rows) {
      expect(await screen.findByText(`${row.layer} · ${row.name}`)).toBeInTheDocument();
    }
    expect(screen.getByRole("link", { name: /Semantic lexicon/ })).toHaveAttribute(
      "href",
      "/admin/lexicon",
    );
    expect(screen.getByRole("link", { name: /Customer Memory/ })).toHaveAttribute(
      "href",
      "/admin/memory-audit",
    );
    // L1 has no console -- it must not render a dead link.
    expect(screen.queryByRole("link", { name: /Identity Graph/ })).toBeNull();
  });

  it("renders every count next to the label that scopes it, never a bare number", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(VIEW)));
    render(<MemoryHub />);
    await screen.findByText("L7 · Semantic lexicon");

    for (const row of VIEW.rows) {
      for (const count of row.counts) {
        const labelEl = screen.getByText(count.label);
        expect(labelEl.closest("li")).toHaveTextContent(count.value);
      }
    }
  });

  it("shows the PII note on L4 and the no-count note on L1", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(VIEW)));
    render(<MemoryHub />);
    expect(
      await screen.findByText(/L4 is the per-customer PII layer by design/),
    ).toBeInTheDocument();
    expect(
      screen.getByText("No live count on this hub and no console of its own."),
    ).toBeInTheDocument();
  });

  // Freshness honesty: the counts are an on-load snapshot, so the page says when
  // it took them rather than implying a live ticker.
  it("stamps the load time so the numbers are not read as continuously live", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(VIEW)));
    render(<MemoryHub />);
    expect(await screen.findByText(/^Counts read at /)).toBeInTheDocument();
  });

  it("surfaces a failed load as an alert instead of an empty layer map", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ detail: "boom" }, 502)));
    render(<MemoryHub />);
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.queryByText("L7 · Semantic lexicon")).toBeNull();
  });
});
