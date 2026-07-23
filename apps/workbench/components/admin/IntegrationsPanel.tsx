"use client";

// Integrations status + in-app reconnect page (0.0.4 S15/S16/S17, FR-23/24/25,
// ADR-0093 admin route group -- but ADMIN-ONLY, a credential surface, narrower than
// the rest of /admin/*). One row per integration: Composio Shopify/QBO/Square
// toolkits, EasyRoutes, SimpleTexting, OpenRouter, and the Gadget mapping endpoint.
// Each shows connection/config status, pinned version (Composio toolkits), last
// successful call, last probe result, and an ACTION cell (S17).
//
// Two reconnect shapes (S17, FR-25):
//   - Composio-managed (kind composio_toolkit): a "Reconnect" button that starts an
//     OAuth redirect flow -- the browser is sent to the provider and returns to the
//     callback route, which verifies a session-bound state and lands back here; the
//     page then re-probes that row. No token ever touches the workbench.
//   - Static-token (EasyRoutes/SimpleTexting/OpenRouter/Gadget): there is NO OAuth and
//     the workbench CANNOT edit deployment env vars, so "reconnect" is GUIDED env
//     rotation + re-probe (gap-review P3): the row names the env var, the operator
//     rotates it in the deployment env, then clicks "Re-probe now". No token value is
//     ever shown, entered, or stored -- only the env-var NAME and instructions.
//
// HONEST BY CONSTRUCTION: "configured" is green only when the credential is present;
// last successful call is "unknown" (nothing records it); last probe is the newest
// scheduled/on-demand probe -- "never probed" until one runs, then an ok/failed/skipped
// badge. No secret is ever shown.
import { useCallback, useEffect, useState } from "react";
import {
  getIntegrationsStatus,
  initiateReconnect,
  reprobeIntegration,
} from "@/lib/api/admin-client";
import { ApiError } from "@/lib/api/http";
import type {
  IntegrationStatus,
  IntegrationsView,
  ProbeResult,
} from "@/lib/bff/admin/integrations";

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

const button: React.CSSProperties = {
  fontSize: "0.75rem",
  padding: "0.2rem 0.5rem",
  cursor: "pointer",
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

function formatWhen(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

// The scheduled/on-demand probe badge (S16, FR-24). null -> "never probed"; ok ->
// green "Healthy"; failed -> red "Failed" + the secret-free reason; the owner-blocked
// "not_configured" -> muted "Skipped". The three states are never conflated.
function ProbeBadge({ probe }: { probe: ProbeResult | null }) {
  if (!probe) return <span style={{ opacity: 0.65 }}>never probed</span>;
  const styles: Record<string, React.CSSProperties> = {
    ok: { ...badgeBase, color: "#0a7", border: "1px solid #0a7" },
    failed: { ...badgeBase, color: "#c0392b", border: "1px solid #c0392b" },
    not_configured: { ...badgeBase, color: "#9a6700", border: "1px solid #9a6700" },
  };
  const labels: Record<string, string> = {
    ok: "Healthy",
    failed: "Failed",
    not_configured: "Skipped",
  };
  const style = styles[probe.status] ?? badgeBase;
  return (
    <span>
      <span style={style}>{labels[probe.status] ?? probe.status}</span>
      <p style={caption}>
        {formatWhen(probe.checkedAt)}
        {probe.status === "failed" && probe.reason ? ` — ${probe.reason}` : ""}
      </p>
    </span>
  );
}

function IntegrationRow({
  row,
  busy,
  onReconnect,
  onReprobe,
}: {
  row: IntegrationStatus;
  busy: boolean;
  onReconnect: (key: string) => void;
  onReprobe: (key: string) => void;
}) {
  const isComposio = row.kind === "composio_toolkit";
  return (
    <tr>
      <td style={cell}>
        <strong>{row.label}</strong>
        <p style={caption}>{row.detail}</p>
        {!isComposio && (
          // Static-token guided panel (FR-25, gap-review P3): instructions only, never
          // a token field. The env-var NAME lives in `detail` above.
          <p style={caption}>
            To reconnect: rotate the credential above in the deployment env, then
            re-probe. The workbench never stores or edits the token.
          </p>
        )}
      </td>
      <td style={cell}>
        <StatusBadge configured={row.configured} />
      </td>
      <td style={cell}>{row.pinnedVersion ?? "—"}</td>
      <td style={cell}>{lastCall(row.lastSuccessfulCall)}</td>
      <td style={cell}>
        <ProbeBadge probe={row.lastProbe} />
      </td>
      <td style={cell}>
        {isComposio && (
          <button
            style={button}
            disabled={busy}
            onClick={() => onReconnect(row.key)}
          >
            Reconnect
          </button>
        )}{" "}
        <button style={button} disabled={busy} onClick={() => onReprobe(row.key)}>
          Re-probe now
        </button>
      </td>
    </tr>
  );
}

export function IntegrationsPanel() {
  const [view, setView] = useState<IntegrationsView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busyKey, setBusyKey] = useState<string | null>(null);

  const load = useCallback(async () => {
    const data = await getIntegrationsStatus();
    setView(data);
  }, []);

  const reprobe = useCallback(
    async (key: string) => {
      setBusyKey(key);
      setActionError(null);
      try {
        await reprobeIntegration(key);
        await load();
        setNote(`Re-probed ${key}.`);
      } catch (err) {
        setActionError(err instanceof ApiError ? err.message : "Re-probe failed.");
      } finally {
        setBusyKey(null);
      }
    },
    [load],
  );

  const reconnect = useCallback(async (key: string) => {
    setBusyKey(key);
    setActionError(null);
    try {
      // Navigate to the provider re-auth URL; the OAuth round-trip returns to the
      // callback route, which lands back here with ?reconnect=<key>.
      const { redirectUrl } = await initiateReconnect(key);
      window.location.href = redirectUrl;
    } catch (err) {
      setActionError(
        err instanceof ApiError ? err.message : "Could not start reconnect.",
      );
      setBusyKey(null);
    }
  }, []);

  // Initial load + handle the OAuth callback return. `?reconnect=state_mismatch` is a
  // REFUSED callback (fail closed) -- show the error, never a success. Any other value
  // is the integration key the callback verified, so re-probe exactly that row.
  useEffect(() => {
    let live = true;
    const returned =
      typeof window !== "undefined"
        ? new URLSearchParams(window.location.search).get("reconnect")
        : null;
    load()
      .then(() => {
        if (!live || !returned) return;
        if (returned === "state_mismatch") {
          setActionError(
            "Reconnect was refused: the callback state did not match. Nothing was changed.",
          );
        } else if (returned !== "ok") {
          void reprobe(returned);
        }
      })
      .catch((err) => {
        if (live) setError(err instanceof ApiError ? err.message : "Failed to load.");
      });
    return () => {
      live = false;
    };
  }, [load, reprobe]);

  if (error) return <p role="alert">{error}</p>;
  if (!view) return <p>Loading…</p>;

  return (
    <div>
      <p style={caption}>
        Active integration backend: <strong>{view.activeDriver}</strong>. Green means
        the credential is present and calls would route live; the Last probe badge is
        the newest health check. Reconnect an expired Composio connection via OAuth, or
        rotate a static token in the deployment env and re-probe.
      </p>
      {actionError && (
        <p role="alert" style={{ color: "#c0392b" }}>
          {actionError}
        </p>
      )}
      {note && <p style={caption}>{note}</p>}
      <table style={{ borderCollapse: "collapse", width: "100%", marginTop: "0.5rem" }}>
        <thead>
          <tr>
            <th style={cell}>Integration</th>
            <th style={cell}>Status</th>
            <th style={cell}>Pinned version</th>
            <th style={cell}>Last successful call</th>
            <th style={cell}>Last probe</th>
            <th style={cell}>Reconnect</th>
          </tr>
        </thead>
        <tbody>
          {view.integrations.map((row) => (
            <IntegrationRow
              key={row.key}
              row={row}
              busy={busyKey === row.key}
              onReconnect={reconnect}
              onReprobe={reprobe}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}
