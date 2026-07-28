"use client";

// Memory Hub (0.0.5 S14, FR-21 / US9 / PAC-5): the L1-L7 layer map of
// docs/architecture/memory-layers.md rendered AS the UI, with live counts and a
// deep link into each layer's console. It sits ABOVE the consoles -- every
// existing deep link still works, this only gives them one entry point.
//
// Read-only, loads on mount (mirrors MetricsPanel / AgentExperienceConsole).
// The counts are an on-load SNAPSHOT, not a ticker, so the page stamps when it
// took them rather than letting a stale tab read as current.
//
// Every count arrives from the BFF as a {label, value} pair and is rendered as
// one, deliberately: the whole hazard of a counts page is a number whose label
// promises more than the query delivers ("L7: 34" beside a prompt carrying 20).
// There is no code path here that can render a value without its scope.
// One caller, one line: the aggregate is read straight through the shared
// getJson helper rather than growing a wrapper in lib/api/admin-client.ts, which
// exists to give the multi-endpoint consoles a typed surface. Move it there if a
// second caller ever appears.
import { useEffect, useState } from "react";
import { ApiError, getJson } from "@/lib/api/http";
import type { MemoryHubRow, MemoryHubView } from "@/lib/bff/admin/memory-hub";

const card: React.CSSProperties = {
  border: "1px solid #e2e2e2",
  borderRadius: "0.5rem",
  padding: "0.75rem 1rem",
};
const heading: React.CSSProperties = { fontSize: "1rem", margin: 0 };
const holds: React.CSSProperties = { fontSize: "0.8125rem", opacity: 0.7, margin: "0.25rem 0 0" };
const list: React.CSSProperties = { listStyle: "none", margin: "0.5rem 0 0", padding: 0 };
const item: React.CSSProperties = {
  display: "flex",
  gap: "0.5rem",
  alignItems: "baseline",
  padding: "0.125rem 0",
};
const countLabel: React.CSSProperties = { fontSize: "0.8125rem", opacity: 0.75 };
const countValue: React.CSSProperties = { fontSize: "1.125rem", fontWeight: 600 };
const noteStyle: React.CSSProperties = {
  fontSize: "0.75rem",
  opacity: 0.7,
  margin: "0.5rem 0 0",
};
const badge: React.CSSProperties = {
  fontSize: "0.75rem",
  border: "1px solid #cfcfcf",
  borderRadius: "0.75rem",
  padding: "0.0625rem 0.5rem",
};

function LayerCard({ row }: { row: MemoryHubRow }) {
  const title = `${row.layer} · ${row.name}`;
  return (
    <li style={card}>
      <div style={{ display: "flex", gap: "0.75rem", alignItems: "baseline" }}>
        <h2 style={heading}>
          {row.href ? <a href={row.href}>{title}</a> : title}
        </h2>
        <span style={badge}>{row.status}</span>
      </div>
      <p style={holds}>{row.holds}</p>
      {row.counts.length > 0 ? (
        <ul style={list}>
          {row.counts.map((count) => (
            <li key={count.label} style={item}>
              <span style={countValue}>{count.value}</span>
              <span style={countLabel}>{count.label}</span>
            </li>
          ))}
        </ul>
      ) : null}
      {row.note ? <p style={noteStyle}>{row.note}</p> : null}
    </li>
  );
}

export function MemoryHub() {
  const [view, setView] = useState<MemoryHubView | null>(null);
  const [readAt, setReadAt] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getJson<MemoryHubView>("/api/admin/memory-hub")
      .then((result) => {
        if (cancelled) return;
        setView(result);
        setReadAt(new Date().toISOString());
      })
      .catch((e) => {
        if (cancelled) return;
        setView(null);
        setError(e instanceof ApiError ? e.message : "Failed to load the memory hub");
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
  if (!view) return null;

  return (
    <section aria-label="Memory layers">
      <p style={noteStyle}>{`Counts read at ${readAt} (UTC). On-load snapshot, not a live ticker — reload to refresh.`}</p>
      <ul style={{ listStyle: "none", margin: "0.75rem 0 0", padding: 0, display: "flex", flexDirection: "column", gap: "0.75rem" }}>
        {view.rows.map((row) => (
          <LayerCard key={row.layer} row={row} />
        ))}
      </ul>
    </section>
  );
}
