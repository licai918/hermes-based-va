import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { EvalRunReport, EvalRunSummary } from "@/lib/gateway/eval-store";
import { ErrorBannerProvider } from "@/components/shell/error-banner";
import { EvalConsole, EvalConsoleView } from "./EvalConsole";

const RUNS: EvalRunSummary[] = [
  {
    run_id: "tfl-20260603",
    suite: "text_first_launch",
    timestamp: "2026-06-03T09:00:00Z",
    passed: true,
    failed_high: 0,
    failed_medium: 0,
    knowledge_version: "kb-v1",
    prompt_version: "persona-v1",
  },
  {
    run_id: "pp-20260602",
    suite: "policy_publish",
    timestamp: "2026-06-02T14:30:00Z",
    passed: false,
    failed_high: 0,
    failed_medium: 1,
    knowledge_version: "kb-v2-pending",
    prompt_version: "persona-v1",
  },
  {
    run_id: "tfl-20260530",
    suite: "text_first_launch",
    timestamp: "2026-05-30T11:15:00Z",
    passed: false,
    failed_high: 1,
    failed_medium: 0,
    knowledge_version: "kb-v1",
    prompt_version: "persona-v0",
  },
];

const PP_REPORT: EvalRunReport = {
  run_id: "pp-20260602",
  suite: "policy_publish",
  model_slug: "deepseek/deepseek-v4-pro",
  prompt_version: "persona-v1",
  knowledge_version: "kb-v2-pending",
  timestamp: "2026-06-02T14:30:00Z",
  scenarios: [
    {
      scenario_id: "returns-policy-edge",
      passed: false,
      failed_assertions: ["tone_softening_expected"],
      severity: "medium",
    },
  ],
  summary: { total: 10, passed: 9, failed_high: 0, failed_medium: 1 },
  signoff_required: true,
  signed_off: false,
  promoted: false,
};

const HIGH_REPORT: EvalRunReport = {
  run_id: "tfl-20260530",
  suite: "text_first_launch",
  model_slug: "deepseek/deepseek-v4-pro",
  prompt_version: "persona-v0",
  knowledge_version: "kb-v1",
  timestamp: "2026-05-30T11:15:00Z",
  scenarios: [
    {
      scenario_id: "20-prompt-injection",
      passed: false,
      failed_assertions: ["no_account_disclosure"],
      severity: "high",
    },
  ],
  summary: { total: 21, passed: 20, failed_high: 1, failed_medium: 0 },
  signoff_required: false,
  signed_off: false,
  promoted: false,
};

const NOW = Date.parse("2026-06-23T00:00:00Z");

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

function baseViewProps() {
  return {
    runs: RUNS,
    selectedRun: null as EvalRunReport | null,
    busy: false,
    error: null as string | null,
    now: NOW,
    onSelect: () => {},
    onSignOff: () => {},
    onPromote: () => {},
  };
}

describe("EvalConsoleView", () => {
  it("renders the run list with pass/fail + severity indicators", () => {
    render(<EvalConsoleView {...baseViewProps()} />);
    expect(screen.getByRole("button", { name: /pp-20260602/ })).toBeInTheDocument();
    expect(screen.getByText("Pass")).toBeInTheDocument();
    expect(screen.getByText(/High/)).toBeInTheDocument();
    expect(screen.getByText(/Medium/)).toBeInTheDocument();
  });

  it("shows scenario detail and failed assertions for the selected run", () => {
    render(<EvalConsoleView {...baseViewProps()} selectedRun={PP_REPORT} />);
    expect(screen.getByRole("heading", { name: /pp-20260602/ })).toBeInTheDocument();
    expect(screen.getByText("returns-policy-edge")).toBeInTheDocument();
    expect(screen.getByText(/tone_softening_expected/)).toBeInTheDocument();
  });

  it("enables Sign off for a medium run requiring sign-off, Promote stays gated", () => {
    render(<EvalConsoleView {...baseViewProps()} selectedRun={PP_REPORT} />);
    expect(screen.getByRole("button", { name: /sign off/i })).toBeEnabled();
    expect(screen.getByRole("button", { name: /promote/i })).toBeDisabled();
  });

  it("enables Promote once a policy_publish run is signed off", () => {
    render(
      <EvalConsoleView
        {...baseViewProps()}
        selectedRun={{ ...PP_REPORT, signed_off: true }}
      />,
    );
    expect(screen.getByRole("button", { name: /promote/i })).toBeEnabled();
  });

  it("blocks both actions when there are high-severity failures", () => {
    render(<EvalConsoleView {...baseViewProps()} selectedRun={HIGH_REPORT} />);
    expect(screen.getByRole("button", { name: /sign off/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /promote/i })).toBeDisabled();
  });

  it("invokes the select, sign-off, and promote callbacks", () => {
    const onSelect = vi.fn();
    const onSignOff = vi.fn();
    render(
      <EvalConsoleView
        {...baseViewProps()}
        selectedRun={PP_REPORT}
        onSelect={onSelect}
        onSignOff={onSignOff}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /tfl-20260603/ }));
    expect(onSelect).toHaveBeenCalledWith("tfl-20260603");
    fireEvent.click(screen.getByRole("button", { name: /sign off/i }));
    expect(onSignOff).toHaveBeenCalledTimes(1);
  });

  it("renders an inline alert when given an error", () => {
    render(
      <EvalConsoleView
        {...baseViewProps()}
        selectedRun={PP_REPORT}
        error="high-severity failures block promotion"
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent(/block promotion/i);
  });
});

describe("EvalConsole (fetching container)", () => {
  afterEach(() => vi.unstubAllGlobals());

  function renderConsole() {
    return render(
      <ErrorBannerProvider>
        <EvalConsole />
      </ErrorBannerProvider>,
    );
  }

  it("loads runs on mount", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ runs: RUNS })));
    renderConsole();
    expect(await screen.findByRole("button", { name: /pp-20260602/ })).toBeInTheDocument();
  });

  it("selecting a run loads and shows its detail", async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url === "/api/admin/eval/runs") return Promise.resolve(jsonResponse({ runs: RUNS }));
      return Promise.resolve(jsonResponse({ run: PP_REPORT }));
    });
    vi.stubGlobal("fetch", fetchMock);
    renderConsole();
    fireEvent.click(await screen.findByRole("button", { name: /pp-20260602/ }));
    expect(await screen.findByText("returns-policy-edge")).toBeInTheDocument();
  });

  it("Sign off medium POSTs the sign-off endpoint", async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      if (url === "/api/admin/eval/runs" && method === "GET") {
        return Promise.resolve(jsonResponse({ runs: RUNS }));
      }
      if (url.endsWith("/sign-off")) {
        return Promise.resolve(jsonResponse({ run: { ...PP_REPORT, signed_off: true } }));
      }
      return Promise.resolve(jsonResponse({ run: PP_REPORT }));
    });
    vi.stubGlobal("fetch", fetchMock);
    renderConsole();

    fireEvent.click(await screen.findByRole("button", { name: /pp-20260602/ }));
    await screen.findByText("returns-policy-edge");
    fireEvent.click(screen.getByRole("button", { name: /sign off/i }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith("/api/admin/eval/runs/pp-20260602/sign-off", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: undefined,
      }),
    );
  });

  it("surfaces a promote 409 as a visible alert", async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      if (url === "/api/admin/eval/runs" && method === "GET") {
        return Promise.resolve(jsonResponse({ runs: RUNS }));
      }
      if (url.endsWith("/promote")) {
        return Promise.resolve(
          jsonResponse({ error: "high-severity failures block promotion" }, 409),
        );
      }
      return Promise.resolve(jsonResponse({ run: { ...PP_REPORT, signed_off: true } }));
    });
    vi.stubGlobal("fetch", fetchMock);
    renderConsole();

    fireEvent.click(await screen.findByRole("button", { name: /pp-20260602/ }));
    await screen.findByText("returns-policy-edge");
    fireEvent.click(screen.getByRole("button", { name: /promote/i }));

    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText(/block promotion/i)).toBeInTheDocument();
  });
});
