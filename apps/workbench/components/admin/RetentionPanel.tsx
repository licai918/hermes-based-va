"use client";

// Customer Memory retention sweep admin panel (0.0.3 S28, FR-30, ADR-0093
// admin route group): last run + rows aged/deleted per class
// (verified/provisional), plus a "Run sweep now" trigger (a governed
// dispatchWrite -- see lib/bff/admin/retention.ts). Loads on mount: a global
// panel, no case_id to key off (mirrors MetricsPanel/AgentExperienceConsole).
//
// 0.0.4 S04 (FR-11): the trigger now QUEUES the sweep for the background worker
// rather than running it inside the request, so the button reports "queued" and
// the counts arrive on the next status read. The sweep -- and the
// workbench_audit_log row this panel's "last run" comes from -- is unchanged;
// retention also runs on a daily cadence now (background_worker.SCHEDULES).
import { useEffect, useState } from "react";
import { getRetentionStatus, triggerRetentionSweep } from "@/lib/api/admin-client";
import { ApiError } from "@/lib/api/http";
import type { RetentionStatus } from "@/lib/bff/admin/retention";

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

function Tile({ title, main, sub }: { title: string; main: string; sub?: string }) {
  return (
    <div style={tile}>
      <p style={label}>{title}</p>
      <p style={value}>{main}</p>
      {sub ? <p style={caption}>{sub}</p> : null}
    </div>
  );
}

function formatLastRun(lastRunAt: string | null): string {
  if (lastRunAt === null) return "Never run";
  const parsed = new Date(lastRunAt);
  return Number.isNaN(parsed.getTime()) ? lastRunAt : parsed.toLocaleString();
}

export function RetentionPanel() {
  const [status, setStatus] = useState<RetentionStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [sweeping, setSweeping] = useState(false);
  const [queued, setQueued] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      setStatus(await getRetentionStatus());
      // This read IS the "Refresh to see the result" the caption asks for, so the
      // caption must not outlive it (S04 fix wave 1, finding 6). Cleared on
      // success only: a failed refresh has not resolved anything.
      setQueued(false);
    } catch (e) {
      setStatus(null);
      setError(e instanceof ApiError ? e.message : "Failed to load retention status");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function runSweep() {
    setSweeping(true);
    setError(null);
    setQueued(false);
    try {
      // S04: this queues a `retention` job; the background worker runs the sweep
      // within a poll interval. Counts land on the next status read, not here.
      await triggerRetentionSweep();
      setQueued(true);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to queue the retention sweep");
    } finally {
      setSweeping(false);
    }
  }

  if (loading) return <p>Loading…</p>;

  return (
    <section aria-label="Retention sweep" style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
      {error ? (
        <p role="alert" style={{ color: "#8a1c1c" }}>
          {error}
        </p>
      ) : null}

      <div style={{ display: "flex", gap: "0.5rem", alignItems: "center", flexWrap: "wrap" }}>
        <button type="button" onClick={() => void runSweep()} disabled={sweeping}>
          {sweeping ? "Queueing sweep…" : "Run sweep now"}
        </button>
        <button type="button" onClick={() => void load()} disabled={loading}>
          Refresh status
        </button>
        {queued ? (
          <span style={caption}>
            Sweep queued — the background worker runs it shortly. Refresh to see the result.
          </span>
        ) : null}
      </div>

      {status ? (
        <>
          <p style={caption}>Last run: {formatLastRun(status.lastRunAt)}</p>
          <div style={grid}>
            <Tile
              title="Verified rows aged out"
              main={String(status.counts.verified)}
              sub={`${status.windowsDays.verified}-day window from last_interaction_at (ADR-0116)`}
            />
            <Tile
              title="Provisional rows aged out"
              main={String(status.counts.provisional)}
              sub={`${status.windowsDays.provisional}-day window from last_interaction_at (ADR-0116 addendum, S28)`}
            />
            <Tile title="Total deleted (last run)" main={String(status.totalDeleted)} />
          </div>
        </>
      ) : null}
    </section>
  );
}
