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
// honestly, and last_successful_call / last_probe stay null until S16 (the panel
// renders "unknown" / "never probed").
import type { HermesApiClient } from "../../gateway/hermes-api-client";
import { HermesApiError } from "../../gateway/hermes-api-client";
import { hermesErrorToProblem } from "../../gateway/hermes-error";
import { json } from "../respond";

// One integration's uniform status. `configured` is the honest credential-presence
// signal (green only when the credential is actually set, not merely that the code
// path exists). `pinnedVersion` is a version string (Composio toolkits only), never
// a secret. `lastSuccessfulCall` is null everywhere in S15 (nothing records it yet)
// and `lastProbe` is null until S16 fills it -- the panel shows "unknown"/"never
// probed" rather than a fabrication.
export interface IntegrationStatus {
  key: string;
  label: string;
  kind: string;
  configured: boolean;
  status: string;
  pinnedVersion: string | null;
  lastSuccessfulCall: string | null;
  lastProbe: string | null;
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
    lastProbe: requireNullableString(r.last_probe, "last_probe"),
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
