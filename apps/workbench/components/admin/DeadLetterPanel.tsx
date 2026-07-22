"use client";

// Dead-letter operator view + governed Replay (0.0.4 S05, FR-13, ADR-0093 admin
// route group). Two tables, because a dead job is not the only way work gets
// stuck:
//
//   "Dead jobs"       -- FR-13's core. Type, payload summary, attempts,
//                        last_error, timestamps, and a per-row Replay with a
//                        confirm. Replay is disabled for a type the server marks
//                        unreplayable (today: l6_review), with the reason shown.
//   "Stuck sends"     -- outbound_send rows that need a human although no
//                        dead-letter row exists (S03/S04). The bucket says what
//                        to do; re-sending is NEVER one of the options here, so
//                        these rows carry no action button.
//
// Loads on mount: a global panel, no id to key off (mirrors RetentionPanel).
import { useEffect, useState } from "react";
import { getDeadLetterView, replayJob } from "@/lib/api/admin-client";
import { ApiError } from "@/lib/api/http";
import type { DeadJob, DeadLetterView, StuckOutbound } from "@/lib/bff/admin/dead-letter";

const caption: React.CSSProperties = { fontSize: "0.75rem", opacity: 0.65, margin: 0 };
const cell: React.CSSProperties = {
  borderBottom: "1px solid #e2e2e2",
  padding: "0.4rem 0.6rem",
  textAlign: "left",
  verticalAlign: "top",
  fontSize: "0.8125rem",
};
const mono: React.CSSProperties = { ...cell, fontFamily: "ui-monospace, monospace" };

// What an operator should DO with each stuck-send bucket. The wording matters
// more than the label: "the customer has it" and "the customer never got it"
// call for opposite actions.
const BUCKET_GUIDANCE: Record<string, string> = {
  send_failed:
    "The provider refused and nothing will retry. The customer never got this — decide whether to contact them by hand.",
  mirror_missing:
    "The customer HAS the message; only the workbench thread row is missing. Do not re-send.",
  stale_intent:
    "A process died mid-delivery, so the job succeeded but the send is unconfirmed. Assume the customer has it.",
};

function formatTime(value: string | null): string {
  if (!value) return "—";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

function DeadJobRow({
  job,
  busy,
  onReplay,
}: {
  job: DeadJob;
  busy: boolean;
  onReplay: (job: DeadJob) => void;
}) {
  return (
    <tr>
      <td style={cell}>{job.type}</td>
      <td style={mono}>{job.jobId}</td>
      <td style={cell}>
        {job.attempts}/{job.maxAttempts}
      </td>
      <td style={cell}>{job.lastError ?? "—"}</td>
      <td style={cell}>
        {JSON.stringify(job.payloadSummary)}
        {job.outbound ? (
          <p style={caption}>
            outbound: {job.outbound.status}
            {job.outbound.lastError ? ` — ${job.outbound.lastError}` : ""}
            {job.outbound.skipCount > 0 ? ` (skipped ${job.outbound.skipCount}×)` : ""}
          </p>
        ) : null}
      </td>
      <td style={cell}>{formatTime(job.updatedAt)}</td>
      <td style={cell}>
        <button
          type="button"
          disabled={!job.replayable || busy}
          title={job.replayBlockedReason ?? undefined}
          onClick={() => onReplay(job)}
        >
          {busy ? "Replaying…" : "Replay"}
        </button>
        {job.replayBlockedReason ? (
          <p style={caption}>{job.replayBlockedReason}</p>
        ) : null}
      </td>
    </tr>
  );
}

function StuckRow({ row }: { row: StuckOutbound }) {
  return (
    <tr>
      <td style={cell}>{row.bucket}</td>
      <td style={cell}>{row.slot}</td>
      <td style={mono}>{row.eventId}</td>
      <td style={mono}>{row.conversationId}</td>
      <td style={cell}>{row.lastError ?? "—"}</td>
      <td style={cell}>{formatTime(row.updatedAt)}</td>
      <td style={cell}>{BUCKET_GUIDANCE[row.bucket] ?? row.status}</td>
    </tr>
  );
}

export function DeadLetterPanel() {
  const [view, setView] = useState<DeadLetterView | null>(null);
  const [loading, setLoading] = useState(true);
  const [replaying, setReplaying] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      setView(await getDeadLetterView());
    } catch (e) {
      setView(null);
      setError(e instanceof ApiError ? e.message : "Failed to load the dead-letter view");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function onReplay(job: DeadJob) {
    // No bulk replay in v1, and one confirm per row: a replay re-runs real work.
    if (!window.confirm(`Replay ${job.type} job ${job.jobId}?`)) return;
    setReplaying(job.jobId);
    setError(null);
    setNotice(null);
    try {
      await replayJob(job.jobId);
      setNotice(`Replayed ${job.jobId} — it is queued again. Refresh to see the result.`);
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to replay the job");
    } finally {
      setReplaying(null);
    }
  }

  if (loading) return <p>Loading…</p>;

  return (
    <section
      aria-label="Dead letters"
      style={{ display: "flex", flexDirection: "column", gap: "1rem" }}
    >
      {error ? (
        <p role="alert" style={{ color: "#8a1c1c" }}>
          {error}
        </p>
      ) : null}
      {notice ? <p style={caption}>{notice}</p> : null}

      <div>
        <button type="button" onClick={() => void load()} disabled={loading}>
          Refresh
        </button>
      </div>

      <h2 style={{ fontSize: "1rem" }}>Dead jobs</h2>
      {view && view.jobs.length > 0 ? (
        <table style={{ borderCollapse: "collapse", width: "100%" }}>
          <thead>
            <tr>
              <th style={cell}>Type</th>
              <th style={cell}>Job</th>
              <th style={cell}>Attempts</th>
              <th style={cell}>Last error</th>
              <th style={cell}>Payload</th>
              <th style={cell}>Last run</th>
              <th style={cell}>Action</th>
            </tr>
          </thead>
          <tbody>
            {view.jobs.map((job) => (
              <DeadJobRow
                key={job.jobId}
                job={job}
                busy={replaying === job.jobId}
                onReplay={(j) => void onReplay(j)}
              />
            ))}
          </tbody>
        </table>
      ) : (
        <p style={caption}>No dead jobs.</p>
      )}

      <h2 style={{ fontSize: "1rem" }}>Stuck sends</h2>
      {view && view.outbound.length > 0 ? (
        <table style={{ borderCollapse: "collapse", width: "100%" }}>
          <thead>
            <tr>
              <th style={cell}>Bucket</th>
              <th style={cell}>Slot</th>
              <th style={cell}>Event</th>
              <th style={cell}>Conversation</th>
              <th style={cell}>Last error</th>
              <th style={cell}>Updated</th>
              <th style={cell}>What to do</th>
            </tr>
          </thead>
          <tbody>
            {view.outbound.map((row) => (
              <StuckRow key={row.idempotencyKey} row={row} />
            ))}
          </tbody>
        </table>
      ) : (
        <p style={caption}>No stuck sends.</p>
      )}
    </section>
  );
}
