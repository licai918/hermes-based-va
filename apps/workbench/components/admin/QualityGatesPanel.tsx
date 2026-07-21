// Minimal admin surfacing for the FR-7/FR-7b knowledge gates + the FR-29 judge
// measurement (S12). These are dev-harness CLI reports (hermes-runtime's
// `hermes_runtime.knowledge.gates`, hermes's `eval_runner.judge_measure`), not
// live-fetched data -- there is no server-side action here (running them needs
// live Postgres + the real embedder/model, which the admin server does not
// have wired). This satisfies NFR-1's carve-out ("dev-harness outputs satisfy
// layer-2 via the admin panel that surfaces them") with a static "how to run +
// last recorded numbers" readout.
//
// ponytail: numbers below are hand-recorded from the last manual run (see
// .superpowers/sdd/0.0.3-S12-report.md), not live. A fuller integration (an
// API route that shells out to the CLIs and a "run now" button) is a real
// upgrade path if this becomes a frequently-checked page -- not built here,
// since the CLIs already need a live DB + embedder/model this admin server
// doesn't have, and static text unblocks the "front-end visible" requirement
// today.

// Stacked (not side-by-side) so the title/command/result never overlap at
// narrow viewport widths -- a flex row with two flexShrink:0 halves squeezed
// and overlapped below ~500px.
const GATE_ROW_STYLE = {
  padding: "0.625rem 0",
  borderBottom: "1px solid #e2e2e2",
} as const;

function chipStyle(color: string) {
  return {
    fontSize: "0.6875rem",
    fontWeight: 600,
    color,
    border: `1px solid ${color}`,
    borderRadius: "999px",
    padding: "0.05rem 0.5rem",
    whiteSpace: "nowrap" as const,
  };
}

function GateChip({ passed }: { passed: boolean }) {
  return (
    <span style={chipStyle(passed ? "#15803d" : "#b91c1c")}>
      {passed ? "PASS" : "FAIL"}
    </span>
  );
}

type GateRow = {
  name: string;
  command: string;
  result: string;
  passed: boolean;
  note?: string;
};

const GATE_ROWS: GateRow[] = [
  {
    name: "Recall@3 (FR-7, synthetic set)",
    command: "python -m hermes_runtime.knowledge.gates recall",
    result: "22/30 = 73% (bar: 80%)",
    passed: false,
    note: "Interim dev-time gate on the spike's 30 synthetic questions. The real ~30 owner-question gate is S32.",
  },
  {
    name: "Hybrid in-turn latency p95 (FR-7b)",
    command: "python -m hermes_runtime.knowledge.gates latency",
    result: "p95 48.4ms @167 chunks (bar: <800ms), embedding inference included",
    passed: true,
  },
  {
    name: "Deadline degrade (FR-7b, forced-slow path)",
    command: "python -m hermes_runtime.knowledge.gates latency",
    result: "governed miss in 815ms, bounded by the 800ms deadline",
    passed: true,
  },
  {
    name: "Judge precision/recall (FR-29)",
    command: "python -m eval_runner.judge_measure --live",
    result: "precision 1.000, recall 1.000, accuracy 0.923 (13 fixtures, 1 undetermined)",
    passed: true,
    note: "See .superpowers/sdd/0.0.3-S27-report.md for the full run.",
  },
];

export function QualityGatesPanel() {
  return (
    <section style={{ marginTop: "2rem" }}>
      <h2 style={{ fontSize: "1.125rem", marginBottom: "0.25rem" }}>Knowledge quality & latency gates</h2>
      <p style={{ fontSize: "0.8125rem", opacity: 0.75, marginBottom: "0.75rem" }}>
        Repeatable CLI commands (ADR-0149), run manually against a live Postgres + the real
        embedder/judge model. Numbers below are the last recorded run, not live.
      </p>
      <div>
        {GATE_ROWS.map((row) => (
          <div key={row.name} style={GATE_ROW_STYLE}>
            <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", flexWrap: "wrap" }}>
              <span style={{ fontWeight: 600 }}>{row.name}</span>
              <GateChip passed={row.passed} />
            </div>
            <div>
              <code style={{ fontSize: "0.75rem", opacity: 0.75 }}>{row.command}</code>
            </div>
            <div style={{ fontSize: "0.8125rem", marginTop: "0.125rem" }}>{row.result}</div>
            {row.note ? (
              <div style={{ fontSize: "0.75rem", opacity: 0.65, marginTop: "0.125rem" }}>{row.note}</div>
            ) : null}
          </div>
        ))}
      </div>
    </section>
  );
}
