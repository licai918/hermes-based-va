// Integrations status page read (0.0.4 S15, FR-23) for the Admin BFF (ADR-0093
// admin route group). Pure and dependency-injected like the sibling admin/*.ts
// modules; the thin app/api/admin/integrations route wraps this with withSession +
// createAdminApiClient.
//
// Dispatches over the SUPERVISOR ADMIN Profile API (deps.ts's createAdminApiClient),
// like admin/dead-letter.ts: toee_integrations is allowlisted for supervisor_admin
// (hermes/toee_hermes/plugin/profiles.py). The single action is agent-excluded on
// the Hermes side (_AGENT_EXCLUDED_ACTIONS) -- never reachable from a live agent's
// tool loop.
//
// ROLE GATING: this page + route are ADMIN-ONLY (lib/auth/access.ts), deliberately
// NARROWER than the supervisor+admin dead-letter operations view -- integrations are
// a CREDENTIAL surface (gap-review P4). The Hermes profile that answers the dispatch
// (supervisor_admin) is orthogonal to the workbench role gate; the admin-only check
// is enforced by withSession before this handler runs.
//
// READ, fail-open (dispatch, not dispatchWrite): a view needs no actor attribution.
// The handler NEVER fabricates a "healthy" -- the backend reports config presence
// honestly, last_successful_call stays null (nothing records it), and last_probe is
// the latest scheduled-probe result (S16, FR-24) or null when none has run yet (the
// panel renders "unknown" / "never probed" / the probe badge).
import type { HermesApiClient } from "../../gateway/hermes-api-client";
import { HermesApiError } from "../../gateway/hermes-api-client";
import { hermesErrorToProblem } from "../../gateway/hermes-error";
import { json } from "../respond";

// The latest scheduled health-probe result for one integration (S16, FR-24). The
// three honest states the probe records: "ok" (reachable + authorized), "failed"
// (credential present but the read errored/was ambiguous -- `reason` explains), and
// "not_configured" (no credential, so the probe was SKIPPED). `reason` is a short,
// secret-free string, non-null only on "failed". `checkedAt` is when it ran.
export interface ProbeResult {
  status: string;
  reason: string | null;
  checkedAt: string;
}

// One integration's uniform status. `configured` is the honest credential-presence
// signal (green only when the credential is actually set, not merely that the code
// path exists). `pinnedVersion` is a version string (Composio toolkits only), never
// a secret. `lastSuccessfulCall` is null everywhere in S15 (nothing records it yet)
// and `lastProbe` is the newest probe result (S16) or null when none has run yet --
// the panel shows "unknown"/"never probed"/the probe badge rather than a fabrication.
export interface IntegrationStatus {
  key: string;
  label: string;
  kind: string;
  configured: boolean;
  status: string;
  pinnedVersion: string | null;
  lastSuccessfulCall: string | null;
  lastProbe: ProbeResult | null;
  detail: string;
}

export interface IntegrationsView {
  // The active external-vendor backend (mock | composio). Composio credentials can
  // be present while the live backend is still `mock`, so this is shown alongside
  // the rows to keep "configured" honest about whether calls actually route live.
  activeDriver: string;
  integrations: IntegrationStatus[];
}

function malformed(detail: string): never {
  throw new HermesApiError(
    "unexpected_error",
    `malformed integrations payload: ${detail}`,
  );
}

function requireString(value: unknown, field: string): string {
  if (typeof value !== "string") malformed(field);
  return value as string;
}

function requireNullableString(value: unknown, field: string): string | null {
  if (value === null || value === undefined) return null;
  if (typeof value !== "string") malformed(field);
  return value as string;
}

function requireBoolean(value: unknown, field: string): boolean {
  if (typeof value !== "boolean") malformed(field);
  return value as boolean;
}

function requireObject(value: unknown, field: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    malformed(field);
  }
  return value as Record<string, unknown>;
}

function requireArray(value: unknown, field: string): unknown[] {
  if (!Array.isArray(value)) malformed(field);
  return value as unknown[];
}

// Strict, like mapIntegration: a null last_probe is a legitimate "never probed",
// but a present-but-malformed one throws (502) rather than being silently dropped
// or painted as a fabricated state.
function mapProbe(raw: unknown): ProbeResult | null {
  if (raw === null || raw === undefined) return null;
  const r = requireObject(raw, "last_probe");
  return {
    status: requireString(r.status, "last_probe.status"),
    reason: requireNullableString(r.reason, "last_probe.reason"),
    checkedAt: requireString(r.checked_at, "last_probe.checked_at"),
  };
}

function mapIntegration(raw: unknown): IntegrationStatus {
  const r = requireObject(raw, "integrations[]");
  return {
    key: requireString(r.key, "key"),
    label: requireString(r.label, "label"),
    kind: requireString(r.kind, "kind"),
    // Strict on purpose: a missing `configured` must NOT default to true, or a
    // backend shape change would paint an owner-blocked integration green.
    configured: requireBoolean(r.configured, "configured"),
    status: requireString(r.status, "status"),
    pinnedVersion: requireNullableString(r.pinned_version, "pinned_version"),
    lastSuccessfulCall: requireNullableString(
      r.last_successful_call,
      "last_successful_call",
    ),
    lastProbe: mapProbe(r.last_probe),
    detail: requireString(r.detail, "detail"),
  };
}

export function mapIntegrationsView(raw: unknown): IntegrationsView {
  const r = requireObject(raw, "root");
  return {
    activeDriver: requireString(r.active_driver, "active_driver"),
    integrations: requireArray(r.integrations, "integrations").map(mapIntegration),
  };
}

export async function handleGetIntegrationsStatusViaApi(
  client: HermesApiClient,
): Promise<Response> {
  try {
    const data = await client.dispatch(
      "toee_integrations",
      "get_integrations_status",
      {},
    );
    return json(mapIntegrationsView(data));
  } catch (err) {
    return hermesErrorToProblem(err);
  }
}

// --- S17 in-app reconnect (FR-25) --------------------------------------------
// Two shapes: Composio OAuth (initiate_reconnect -> a provider re-auth URL) and,
// for BOTH shapes' completion, an on-demand re-probe (reprobe_now). Both are
// governed WRITES: dispatchWrite, fail-closed on a missing actor. The acting admin
// rides HermesApiClient.actorAccountId from the signed-in session (ADR-0148) -- it
// is never a request param, and the routes never read one.

export interface ReconnectLink {
  integrationKey: string;
  redirectUrl: string;
}

export interface ReprobeReceipt {
  integrationKey: string;
  status: string;
  reason: string | null;
}

function mapReconnectLink(raw: unknown): ReconnectLink {
  const r = requireObject(raw, "root");
  // Strict: a null/absent redirect_url is a fail-closed backend (owner-blocked or a
  // wrong SDK guess), NOT a usable link -- surface it as an error, never navigate.
  return {
    integrationKey: requireString(r.integration_key, "integration_key"),
    redirectUrl: requireString(r.redirect_url, "redirect_url"),
  };
}

function mapReprobeReceipt(raw: unknown): ReprobeReceipt {
  const r = requireObject(raw, "root");
  return {
    integrationKey: requireString(r.integration_key, "integration_key"),
    status: requireString(r.status, "status"),
    reason: requireNullableString(r.reason, "reason"),
  };
}

// Only the three Composio-managed connections have an OAuth reconnect. Guarded here
// AND server-side (the handler rejects a non-Composio key), so a crafted body cannot
// coax a link for a static-token integration.
const COMPOSIO_KEYS = new Set(["shopify", "qbo", "square"]);

export async function handleInitiateReconnectViaApi(
  client: HermesApiClient,
  integrationKey: unknown,
  callbackUrl: string,
): Promise<Response> {
  if (typeof integrationKey !== "string" || !COMPOSIO_KEYS.has(integrationKey)) {
    return hermesErrorToProblem(
      new HermesApiError("not_found", "unknown Composio integration"),
    );
  }
  try {
    const data = await client.dispatchWrite(
      "toee_integrations",
      "initiate_reconnect",
      { integration_key: integrationKey, callback_url: callbackUrl },
    );
    return json(mapReconnectLink(data));
  } catch (err) {
    return hermesErrorToProblem(err);
  }
}

export async function handleReprobeNowViaApi(
  client: HermesApiClient,
  integrationKey: unknown,
): Promise<Response> {
  if (typeof integrationKey !== "string" || integrationKey === "") {
    return hermesErrorToProblem(
      new HermesApiError("not_found", "integrationKey is required"),
    );
  }
  try {
    const data = await client.dispatchWrite("toee_integrations", "reprobe_now", {
      integration_key: integrationKey,
    });
    return json(mapReprobeReceipt(data));
  } catch (err) {
    return hermesErrorToProblem(err);
  }
}
