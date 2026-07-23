"use client";

// Integrations status page (0.0.4 S15, FR-23, ADR-0093 admin route group -- but
// ADMIN-ONLY, a credential surface, narrower than the rest of /admin/*). One row per
// integration: Composio Shopify/QBO/Square toolkits, EasyRoutes, SimpleTexting,
// OpenRouter, and the Gadget mapping endpoint. Each shows connection/config status,
// pinned version (Composio toolkits), last successful call, and last probe result.
//
// HONEST BY CONSTRUCTION: "configured" is green only when the credential is actually
// present (the backend never fabricates a "healthy"); last successful call is
// "unknown" because nothing records it yet; last probe is "never probed" until S16's
// scheduled probes fill it. No secret is ever shown -- only booleans, version pins,
// and human detail. Loads on mount: a global panel, no id to key off (mirrors
// MetricsPanel / DeadLetterPanel).
import { useEffect, useState } from "react";
import { getIntegrationsStatus } from "@/lib/api/admin-client";
import { ApiError } from "@/lib/api/http";
import type { IntegrationStatus, IntegrationsView } from "@/lib/bff/admin/integrations";

const caption: React.CSSProperties = { fontSize: "0.75rem", opacity: 0.65, margin: 0 };
const cell: React.CSSProperties = {
  borderBottom: "1px solid #e2e2e2",
  padding: "0.4rem 0.6rem",
  textAlign: "left",
  verticalAlign: "top",
  fontSize: "0.8125rem",
};

const badgeBase: React.CSSProperties = {
  fontSize: "0.6875rem",
  fontWeight: 600,
  borderRadius: "999px",
  padding: "0.1rem 0.5rem",
  whiteSpace: "nowrap",
};

function StatusBadge({ configured }: { configured: boolean }) {
  const style: React.CSSProperties = configured
    ? { ...badgeBase, color: "#0a7", border: "1px solid #0a7" }
    : { ...badgeBase, color: "#9a6700", border: "1px solid #9a6700" };
  return <span style={style}>{configured ? "Configured" : "Not configured"}</span>;
}

// last_successful_call is null everywhere in S15 (nothing records it yet) -> honest
// "unknown", never a fabricated timestamp.
function lastCall(value: string | null): string {
  if (!value) return "unknown";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

// last_probe is null until S16's scheduled probes land -> "never probed".
function lastProbe(value: string | null): string {
  if (!value) return "never probed";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

function IntegrationRow({ row }: { row: IntegrationStatus }) {
  return (
    <tr>
      <td style={cell}>
        <strong>{row.label}</strong>
        <p style={caption}>{row.detail}</p>
      </td>
      <td style={cell}>
        <StatusBadge configured={row.configured} />
      </td>
      <td style={cell}>{row.pinnedVersion ?? "—"}</td>
      <td style={cell}>{lastCall(row.lastSuccessfulCall)}</td>
      <td style={cell}>{lastProbe(row.lastProbe)}</td>
    </tr>
  );
}

export function IntegrationsPanel() {
  const [view, setView] = useState<IntegrationsView | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    getIntegrationsStatus()
      .then((data) => {
        if (live) setView(data);
      })
      .catch((err) => {
        if (live) setError(err instanceof ApiError ? err.message : "Failed to load.");
      });
    return () => {
      live = false;
    };
  }, []);

  if (error) return <p role="alert">{error}</p>;
  if (!view) return <p>Loading…</p>;

  return (
    <div>
      <p style={caption}>
        Active integration backend: <strong>{view.activeDriver}</strong>. Green means
        the credential is present and calls would route live; probes arrive in S16.
      </p>
      <table style={{ borderCollapse: "collapse", width: "100%", marginTop: "0.5rem" }}>
        <thead>
          <tr>
            <th style={cell}>Integration</th>
            <th style={cell}>Status</th>
            <th style={cell}>Pinned version</th>
            <th style={cell}>Last successful call</th>
            <th style={cell}>Last probe</th>
          </tr>
        </thead>
        <tbody>
          {view.integrations.map((row) => (
            <IntegrationRow key={row.key} row={row} />
          ))}
        </tbody>
      </table>
    </div>
  );
}
