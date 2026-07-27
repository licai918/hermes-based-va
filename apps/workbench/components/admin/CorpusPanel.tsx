"use client";

// S11 (FR-6, PRD): corpus status + retrieval probe, a SIBLING section on the
// existing /admin/knowledge surface (ADR-0087) -- it does not touch the policy
// slot master-detail above it.
//
// 0.0.4 S04 (FR-11) takes the ponytail upgrade S11 named: re-ingest was a v1
// stub that printed a CLI command, because the ingest work (corpus artifact +
// embedding model) is far too heavy for the dispatch server's request thread.
// It now enqueues an `ingest` job, which the BACKGROUND WORKER runs -- the
// substrate S11 was missing. The panel reads the job's status back below.
import type { FormEvent } from "react";
import { useCallback, useEffect, useState } from "react";
import { useErrorBanner } from "@/components/shell/error-banner";
import { getCorpusStatus, probeKnowledge, triggerCorpusReingest } from "@/lib/api/admin-client";
import { ApiError } from "@/lib/api/http";
import type { CorpusStatus, ProbeResult } from "@/lib/bff/admin/knowledge";

const fieldStyle = { display: "block", marginBottom: "0.75rem" } as const;

export function CorpusPanel() {
  const { showError } = useErrorBanner();
  const [status, setStatus] = useState<CorpusStatus | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [loadingStatus, setLoadingStatus] = useState(false);

  const [reingesting, setReingesting] = useState(false);

  const [query, setQuery] = useState("");
  const [results, setResults] = useState<ProbeResult[] | null>(null);
  const [probing, setProbing] = useState(false);
  const [probeError, setProbeError] = useState<string | null>(null);

  const loadStatus = useCallback(async () => {
    setLoadingStatus(true);
    setStatusError(null);
    try {
      setStatus(await getCorpusStatus());
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : "Failed to load corpus status";
      setStatusError(msg);
      showError(msg);
    } finally {
      setLoadingStatus(false);
    }
  }, [showError]);

  useEffect(() => {
    loadStatus();
  }, [loadStatus]);

  async function runReingest() {
    setReingesting(true);
    setStatusError(null);
    try {
      await triggerCorpusReingest();
      await loadStatus(); // the readback: the queued job shows up immediately
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : "Failed to queue the re-ingest";
      setStatusError(msg);
      showError(msg);
    } finally {
      setReingesting(false);
    }
  }

  async function runProbe(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!query.trim()) return;
    setProbing(true);
    setProbeError(null);
    try {
      setResults(await probeKnowledge(query));
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : "Query failed";
      setProbeError(msg);
      showError(msg);
    } finally {
      setProbing(false);
    }
  }

  return (
    <section style={{ marginTop: "2rem", borderTop: "1px solid #e2e2e2", paddingTop: "1.5rem" }}>
      <h2 style={{ fontSize: "1.125rem", margin: "0 0 0.75rem" }}>Corpus status</h2>

      {statusError ? (
        <p role="alert" style={{ color: "#8a1c1c" }}>
          {statusError}
        </p>
      ) : null}

      {status ? (
        <>
          <dl
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(3, minmax(6rem, auto))",
              gap: "0.125rem 1.5rem",
              margin: "0 0 0.75rem",
            }}
          >
            <dt style={{ fontWeight: 600 }}>Docs</dt>
            <dt style={{ fontWeight: 600 }}>Chunks</dt>
            <dt style={{ fontWeight: 600 }}>Last ingest</dt>
            <dd style={{ margin: 0 }}>{status.docCount}</dd>
            <dd style={{ margin: 0 }}>{status.chunkCount}</dd>
            <dd style={{ margin: 0 }}>{status.lastIngestAt ?? "never"}</dd>
          </dl>

          {status.byType.length > 0 ? (
            <table style={{ marginBottom: "0.75rem", borderCollapse: "collapse" }}>
              <thead>
                <tr>
                  <th style={{ textAlign: "left", paddingRight: "1rem" }}>Type</th>
                  <th style={{ textAlign: "left" }}>Count</th>
                </tr>
              </thead>
              <tbody>
                {status.byType.map((row) => (
                  <tr key={row.pageType}>
                    <td style={{ paddingRight: "1rem" }}>{row.pageType}</td>
                    <td>{row.count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
        </>
      ) : null}

      <div style={{ display: "flex", gap: "0.5rem", alignItems: "center", flexWrap: "wrap", marginBottom: "1.5rem" }}>
        <button type="button" onClick={loadStatus} disabled={loadingStatus}>
          Refresh status
        </button>
        <button type="button" onClick={() => void runReingest()} disabled={reingesting}>
          {reingesting ? "Queueing re-ingest…" : "Re-ingest corpus"}
        </button>
        {status?.lastIngestJob ? (
          <span style={{ fontSize: "0.8125rem", opacity: 0.75 }}>
            Last re-ingest job: {status.lastIngestJob.status}
            {status.lastIngestJob.queuedAt ? ` (queued ${status.lastIngestJob.queuedAt})` : ""}
            {status.lastIngestJob.lastError ? ` — ${status.lastIngestJob.lastError}` : ""}
          </span>
        ) : (
          <span style={{ fontSize: "0.8125rem", opacity: 0.75 }}>No re-ingest queued yet</span>
        )}
      </div>

      <h2 style={{ fontSize: "1.125rem", margin: "0 0 0.75rem" }}>Test a query</h2>
      <form onSubmit={runProbe} style={fieldStyle}>
        <label htmlFor="probe-query" style={{ display: "block", fontWeight: 600, marginBottom: "0.25rem" }}>
          Query
        </label>
        <div style={{ display: "flex", gap: "0.5rem" }}>
          <input
            id="probe-query"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Ask a question the public site should answer"
            style={{ flex: 1 }}
          />
          <button type="submit" disabled={probing}>
            Search
          </button>
        </div>
      </form>

      {probeError ? (
        <p role="alert" style={{ color: "#8a1c1c" }}>
          {probeError}
        </p>
      ) : null}

      {results ? (
        results.length === 0 ? (
          <p>No matches.</p>
        ) : (
          <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
            {results.map((r, i) => (
              <li key={`${r.title}-${i}`} style={{ marginBottom: "0.75rem" }}>
                <div style={{ fontWeight: 600 }}>{r.title}</div>
                {r.url ? (
                  <div>
                    <a href={r.url}>{r.url}</a>
                  </div>
                ) : null}
                <p style={{ margin: "0.25rem 0 0" }}>{r.snippet}</p>
              </li>
            ))}
          </ul>
        )
      ) : null}
    </section>
  );
}
