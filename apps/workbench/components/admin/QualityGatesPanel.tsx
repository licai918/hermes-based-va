"use client";

// Knowledge quality & latency gates panel (S12 origin; 0.0.4 S23, FR-32). The
// hand-copied static numbers are gone: this now reads the LATEST gate-report
// artifacts live (governed admin read, /api/admin/quality-gates) -- the knowledge
// recall/latency harness (`hermes_runtime.knowledge.gates`) and the S20 advisory
// judge (`hermes_runtime.advisory_judge_report`), each emitting a JSON artifact per
// run. Each report card shows the real rows + "as of <ts>" + source provenance.
//
// Honesty (FR-32), mirroring the MetricsPanel honored-rate tile (S22): no artifact
// -> an honest "not yet available" empty state, never a fabricated number; an
// artifact older than the stale threshold -> an "as of <ts> - may be stale" label
// rather than presenting it as current.
import { useEffect, useState } from "react";
import { getQualityGatesReports } from "@/lib/api/admin-client";
import { ApiError } from "@/lib/api/http";
import type { QualityGateReport, QualityGatesView } from "@/lib/bff/admin/quality-gates";

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

// passed=null is advisory (the judge report, FR-29): no PASS/FAIL, an ADVISORY chip.
function GateChip({ passed }: { passed: boolean | null }) {
  if (passed === null) return <span style={chipStyle("#a16207")}>ADVISORY</span>;
  return (
    <span style={chipStyle(passed ? "#15803d" : "#b91c1c")}>{passed ? "PASS" : "FAIL"}</span>
  );
}

function asOfLine(report: QualityGateReport): string {
  const when = new Date(report.generatedAt).toLocaleString();
  const staleNote = report.stale ? " — may be stale" : "";
  return `as of ${when}${staleNote}`;
}

function ReportCard({ report }: { report: QualityGateReport }) {
  return (
    <div style={{ marginTop: "1rem" }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: "0.5rem", flexWrap: "wrap" }}>
        <span
          style={{
            fontSize: "0.75rem",
            fontWeight: 600,
            opacity: report.stale ? 0.9 : 0.6,
            color: report.stale ? "#a16207" : undefined,
          }}
        >
          {asOfLine(report)}
        </span>
        {report.sourceRun ? (
          /^https?:\/\//.test(report.sourceRun) ? (
            <a href={report.sourceRun} style={{ fontSize: "0.75rem" }} target="_blank" rel="noreferrer">
              source run
            </a>
          ) : (
            <span style={{ fontSize: "0.75rem", opacity: 0.6 }}>{report.sourceRun}</span>
          )
        ) : (
          <code style={{ fontSize: "0.7rem", opacity: 0.55 }}>{report.source}</code>
        )}
      </div>
      {report.rows.map((row) => (
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
  );
}

export function QualityGatesPanel() {
  const [view, setView] = useState<QualityGatesView | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getQualityGatesReports()
      .then((result) => {
        if (!cancelled) setView(result);
      })
      .catch((e) => {
        if (cancelled) return;
        setView(null);
        setError(e instanceof ApiError ? e.message : "Failed to load gate reports");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <section style={{ marginTop: "2rem" }}>
      <h2 style={{ fontSize: "1.125rem", marginBottom: "0.25rem" }}>Knowledge quality & latency gates</h2>
      <p style={{ fontSize: "0.8125rem", opacity: 0.75, marginBottom: "0.75rem" }}>
        Repeatable CLI gates (ADR-0149), run against a live Postgres + the real embedder/judge
        model. Numbers below are the latest recorded run of each gate, read live from its report
        artifact.
      </p>
      {loading ? <p>Loading…</p> : null}
      {error ? (
        <p role="alert" style={{ color: "#8a1c1c" }}>
          {error}
        </p>
      ) : null}
      {!loading && !error && view && view.reports.length === 0 ? (
        <p style={{ fontSize: "0.8125rem", opacity: 0.7 }}>
          No gate reports available yet — run a gate to populate this panel.
        </p>
      ) : null}
      {!loading && !error && view
        ? view.reports.map((report) => <ReportCard key={report.kind} report={report} />)
        : null}
    </section>
  );
}
