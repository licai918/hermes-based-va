"use client";

// Aggregate-metrics admin panel (0.0.3 S26, FR-28, ADR-0093 admin route
// group): memory injection rate, slots-populated distribution, honored rate
// (advisory, judge-sampled -- NEVER gating), merge count, correction count,
// proposal accept/dismiss rate, knowledge found rate, and self-service usage.
// Live SQL aggregations everywhere except honored rate: memory injection,
// knowledge found, slots distribution, merge count, correction count, proposal
// outcomes, and -- since 0.0.4 S21 (FR-30) -- self-service usage and L6
// confirmed entries, now real once-per-action counters (metric_event) rather
// than the earlier proxies. Honored rate is now live too (0.0.4 S22, FR-31): the
// scheduled honored_rate judge job persists an aggregate this tile shows with
// "as of" provenance -- or an honest "Not yet computed" before the first run,
// never a fabricated number. Loads on mount: a global panel, no case_id to key
// off (mirrors AgentExperienceConsole).
import { useEffect, useState } from "react";
import { getAggregateMetrics } from "@/lib/api/admin-client";
import { ApiError } from "@/lib/api/http";
import type { AggregateMetrics } from "@/lib/bff/admin/metrics";

const tile: React.CSSProperties = {
  border: "1px solid #e2e2e2",
  borderRadius: "0.5rem",
  padding: "0.75rem 1rem",
  minWidth: "12rem",
};
const grid: React.CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  gap: "0.75rem",
};
const label: React.CSSProperties = { fontSize: "0.8125rem", opacity: 0.7, margin: 0 };
const value: React.CSSProperties = { fontSize: "1.5rem", fontWeight: 600, margin: "0.125rem 0" };
const caption: React.CSSProperties = { fontSize: "0.75rem", opacity: 0.65, margin: 0 };

function pct(rate: number | null): string {
  return rate === null ? "—" : `${Math.round(rate * 1000) / 10}%`;
}

// Honored-rate provenance line. When live, make the partial sample legible (rate
// is over `sampleSize` of `candidateTotal`, not the whole population) plus the
// "as of" run time; when not yet computed, the honest label from the BFF.
function honoredSub(h: AggregateMetrics["honoredRate"]): string {
  if (!h.live) return h.label;
  const asOf = h.asOf ? new Date(h.asOf).toLocaleDateString() : "unknown date";
  return `${h.sampleSize} / ${h.candidateTotal} recent turns sampled · as of ${asOf}`;
}

function Tile({ title, main, sub }: { title: string; main: string; sub?: string }) {
  return (
    <div style={tile}>
      <p style={label}>{title}</p>
      <p style={value}>{main}</p>
      {sub ? <p style={caption}>{sub}</p> : null}
    </div>
  );
}

export function MetricsPanel() {
  const [metrics, setMetrics] = useState<AggregateMetrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getAggregateMetrics()
      .then((result) => {
        if (!cancelled) setMetrics(result);
      })
      .catch((e) => {
        if (cancelled) return;
        setMetrics(null);
        setError(e instanceof ApiError ? e.message : "Failed to load aggregate metrics");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) return <p>Loading…</p>;
  if (error) {
    return (
      <p role="alert" style={{ color: "#8a1c1c" }}>
        {error}
      </p>
    );
  }
  if (!metrics) return null;

  const dist = metrics.slotsPopulatedDistribution;

  return (
    <section aria-label="Aggregate metrics" style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
      <div style={grid}>
        <Tile
          title="Memory injection rate"
          main={pct(metrics.memoryInjection.rate)}
          sub={`${metrics.memoryInjection.injected} / ${metrics.memoryInjection.total} turns`}
        />
        <Tile
          title="Knowledge found rate"
          main={pct(metrics.knowledgeSearch.rate)}
          sub={`${metrics.knowledgeSearch.found} / ${metrics.knowledgeSearch.total} searches`}
        />
        <Tile
          title="Honored rate"
          main={metrics.honoredRate.live ? pct(metrics.honoredRate.rate) : "Not yet computed"}
          sub={honoredSub(metrics.honoredRate)}
        />
        <Tile title="Merge count" main={String(metrics.mergeCount)} sub="customer_memory_merge_audit" />
        <Tile title="Correction count" main={String(metrics.correctionCount)} sub="employee_confirmed writes" />
        <Tile
          title="Proposal accept / dismiss"
          main={`${metrics.proposalOutcomes.accepted} / ${metrics.proposalOutcomes.dismissed}`}
          sub={`accept rate ${pct(metrics.proposalOutcomes.rate)} (accept inferred from employee_confirmed writes)`}
        />
        <Tile
          title="Self-service usage"
          main={String(metrics.selfServiceUsage)}
          sub="customer self-service preference clears"
        />
        <Tile
          title="L6 confirmed entries"
          main={String(metrics.l6ConfirmedEntries)}
          sub="agent-experience confirm events"
        />
      </div>

      <div>
        <h2 style={{ fontSize: "1.125rem", margin: "0 0 0.5rem" }}>Slots-populated distribution</h2>
        <table style={{ borderCollapse: "collapse" }}>
          <thead>
            <tr>
              <th style={{ textAlign: "left", padding: "0.25rem 1rem 0.25rem 0", borderBottom: "1px solid #ccc" }}>
                Slots populated
              </th>
              <th style={{ textAlign: "left", padding: "0.25rem 1rem 0.25rem 0", borderBottom: "1px solid #ccc" }}>
                Customers
              </th>
            </tr>
          </thead>
          <tbody>
            {(["1", "2", "3", "4"] as const).map((n) => (
              <tr key={n}>
                <td style={{ padding: "0.25rem 1rem 0.25rem 0" }}>{n}</td>
                <td style={{ padding: "0.25rem 1rem 0.25rem 0" }}>{dist[n]}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
