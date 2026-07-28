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
import type { AggregateMetrics, LatencyTile } from "@/lib/bff/admin/metrics";

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

// Honored-rate provenance line. When live, keep the two stages distinct so the
// ratio isn't misread as "only looked at 40 of 200": `sampleSize` were
// determinately SCORED, `undetermined` were sampled but not determinately scored,
// and `candidateTotal` is the ELIGIBLE population (threads with customer memory on
// file, pre-cap) -- not "memory injected at reply time". Plus the "as of" run time;
// when not yet computed, the honest label from the BFF.
function honoredSub(h: AggregateMetrics["honoredRate"]): string {
  if (!h.live) return h.label;
  const asOf = h.asOf ? new Date(h.asOf).toLocaleDateString() : "unknown date";
  const undetermined = h.undetermined ?? 0;
  return `${h.sampleSize} scored · ${undetermined} undetermined of ${h.candidateTotal} turns with customer memory on file · as of ${asOf}`;
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

// --- S18 (FR-26): per-layer read latency + the total-vs-SLO tile -------------
// Measurement only. This slice ships NO deadline (S19 owns enforcement), so a
// tile with no budget shows its percentiles and passes no judgement, and a tile
// with no samples says so rather than showing a 0ms that would read as the best
// possible latency. A breach is rendered as words + colour, not as one more
// number the reader has to compare by eye.

function ms(v: number | null): string {
  return v === null ? "—" : `${Math.round(v * 100) / 100} ms`;
}

function LatencyTileView({ tile: t, notMeasured }: { tile: LatencyTile; notMeasured: string }) {
  const measured = t.samples > 0;
  const breached = t.breached === true;
  return (
    <div
      data-metric={t.metric}
      style={{
        ...tile,
        borderColor: breached ? "#8a1c1c" : "#e2e2e2",
        borderWidth: breached ? 2 : 1,
      }}
    >
      <p style={label}>
        {t.layer} · {t.label}
      </p>
      <p style={{ ...value, color: breached ? "#8a1c1c" : undefined }}>
        {measured ? `p95 ${ms(t.p95Ms)}` : "Not yet measured"}
      </p>
      <p style={caption}>
        {measured
          ? `p50 ${ms(t.p50Ms)} · ${t.samples} samples${
              t.budgetMs === null ? " · no budget (S19)" : ` · budget ${ms(t.budgetMs)}`
            }`
          : notMeasured}
      </p>
      {breached ? (
        <p style={{ ...caption, color: "#8a1c1c", fontWeight: 600 }}>
          Over budget — p95 {ms(t.p95Ms)} exceeds {ms(t.budgetMs)}
        </p>
      ) : null}
    </div>
  );
}

function LatencySection({ latency }: { latency: AggregateMetrics["latency"] }) {
  return (
    <section aria-label="Per-layer memory read latency" style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
      <h2 style={{ fontSize: "1.125rem", margin: 0 }}>Per-layer memory read latency</h2>
      <p style={caption}>
        SLO: pre-turn reads (L4 + L6 + L7) at or under {ms(latency.sloP95Ms)} p95. L5 knowledge
        retrieval is measured against its own retrieval deadline and excluded from that total; the
        provisional merge is a write and is excluded too.
      </p>
      <div style={grid}>
        <LatencyTileView tile={latency.total} notMeasured={latency.notMeasuredLabel} />
        {latency.layers.map((t) => (
          <LatencyTileView key={t.metric} tile={t} notMeasured={latency.notMeasuredLabel} />
        ))}
      </div>
    </section>
  );
}

// --- S22 (FR-34a): the memory-lifecycle block + the read-only knob panel -----
//
// Counts, not rates, and that is deliberate: nothing records how many L4 writes
// were ATTEMPTED, so a conflict or pollution "rate" would have an invented
// denominator -- a percentage that reads as accuracy and is not. Each tile shows
// its number beside the `detail` the BFF refused to let travel without it.

function LifecycleTile({
  id,
  title,
  main,
  detail,
}: {
  id: string;
  title: string;
  main: string;
  detail: string;
}) {
  return (
    <div data-lifecycle={id} style={{ ...tile, maxWidth: "20rem" }}>
      <p style={label}>{title}</p>
      <p style={value}>{main}</p>
      <p style={caption}>{detail}</p>
    </div>
  );
}

function LifecycleSection({
  lifecycle,
  deletion,
}: {
  lifecycle: AggregateMetrics["lifecycle"];
  deletion: AggregateMetrics["deletionSuccess"];
}) {
  return (
    <section
      aria-label="Memory lifecycle"
      style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}
    >
      <h2 style={{ fontSize: "1.125rem", margin: 0 }}>Memory lifecycle</h2>
      <div style={grid}>
        {lifecycle.map((c) => (
          <LifecycleTile
            key={c.key}
            id={c.key}
            title={c.label}
            // `null` is "nothing feeds this yet", which is not the same fact as
            // zero and must not be rendered as one.
            main={c.value === null ? "Not recorded" : String(c.value)}
            detail={c.detail}
          />
        ))}
        {/* S11's FR-14 tile, placed here (S22 owns the placement). Components,
            not just the rate: residue (a row the erase left) and re-appearance
            (a row written afterwards) are different failures, and a rate over
            zero erases is "not computed", never a perfect score. */}
        <LifecycleTile
          id="deletion_success"
          title="Erases that stayed erased"
          main={
            deletion.rate === null
              ? "No erases yet"
              : `${pct(deletion.rate)} of ${deletion.erasedBindings}`
          }
          detail={
            `${deletion.flaggedBindings} flagged — ${deletion.residueBindings} residue, ` +
            `${deletion.reappearedBindings} re-appeared · watched for ${deletion.windowDays} days · ` +
            deletion.label
          }
        />
      </div>
    </section>
  );
}

// D14: READ-ONLY, and the section says so. There is deliberately no control here
// -- a knob moves by deploy-time config commit whose audit trail is git history
// (NFR-3), and a toggle that looked mutable and was not would be worse than no
// panel at all.
function KnobSection({ knobs }: { knobs: AggregateMetrics["knobs"] }) {
  return (
    <section
      aria-label="Knob panel"
      style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}
    >
      <h2 style={{ fontSize: "1.125rem", margin: 0 }}>Knobs (read-only)</h2>
      <p style={caption}>
        {knobs
          ? knobs.label
          : "Read-only. Knob values are not reported by this backend — the mock driver " +
            "does not run them. On a Postgres deployment this panel lists every one."}
      </p>
      {knobs ? (
        <table style={{ borderCollapse: "collapse" }}>
          <thead>
            <tr>
              <th style={{ textAlign: "left", padding: "0.25rem 1rem 0.25rem 0", borderBottom: "1px solid #ccc" }}>
                Knob
              </th>
              <th style={{ textAlign: "left", padding: "0.25rem 1rem 0.25rem 0", borderBottom: "1px solid #ccc" }}>
                Value
              </th>
              <th style={{ textAlign: "left", padding: "0.25rem 1rem 0.25rem 0", borderBottom: "1px solid #ccc" }}>
                Changed by editing
              </th>
            </tr>
          </thead>
          <tbody>
            {knobs.knobs.map((knob) => (
              <tr key={knob.key} data-knob={knob.key}>
                <td style={{ padding: "0.35rem 1rem 0.35rem 0", verticalAlign: "top" }}>
                  <div style={{ fontWeight: 600 }}>{knob.label}</div>
                  <div style={caption}>{knob.note}</div>
                </td>
                <td style={{ padding: "0.35rem 1rem 0.35rem 0", verticalAlign: "top", fontWeight: 600 }}>
                  {knob.value}
                </td>
                <td style={{ padding: "0.35rem 1rem 0.35rem 0", verticalAlign: "top" }}>
                  <code>
                    {knob.source}.{knob.key}
                  </code>
                  {knob.env ? <div style={caption}>env override: {knob.env}</div> : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </section>
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

      <LatencySection latency={metrics.latency} />

      <LifecycleSection lifecycle={metrics.lifecycle} deletion={metrics.deletionSuccess} />

      <KnobSection knobs={metrics.knobs} />

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
