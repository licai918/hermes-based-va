// L6 Agent-experience admin list read (0.0.3 S22, FR-23) for the Admin BFF
// (ADR-0093 admin route group). Pure and dependency-injected like the sibling
// admin/*.ts modules; the thin app/api/admin/agent-experience route wraps this
// with withSession + a per-profile client.
//
// Dispatches over the Internal Copilot Profile API (HERMES_COPILOT_API_URL/
// TOKEN), NOT the Supervisor Admin Profile API createAdminApiClient (deps.ts)
// uses elsewhere in this folder: toee_agent_experience is allowlisted for
// internal_copilot only (hermes/toee_hermes/plugin/profiles.py) -- the same
// reason admin/memory-audit.ts reaches that profile instead of the supervisor
// one. Admin-gating (ADR-0093) still comes from the BFF route itself
// (/api/admin/* + withSession's role check), not from which Hermes profile
// answers the dispatch.
//
// READ, fail-open (dispatch, not dispatchWrite): a supervisor can view the
// proposal list with no actor attribution needed, same convention as
// handleGetMemoryAuditViaApi. list_agent_experience is admin-only on the
// Hermes side too (_AGENT_EXCLUDED_ACTIONS) -- never reachable from the
// copilot model's own tool-calling loop. This slice is read-only: S24 adds
// the Accept/Reject decision actions on top of this same list.
import type { HermesApiClient } from "../../gateway/hermes-api-client";
import { HermesApiError } from "../../gateway/hermes-api-client";
import { hermesErrorToProblem } from "../../gateway/hermes-error";
import type {
  AgentExperienceEntry,
  AgentExperienceKind,
  AgentExperienceStatus,
} from "../../gateway/types";
import { json } from "../respond";

const KINDS: readonly AgentExperienceKind[] = ["note", "procedure"];
const STATUSES: readonly AgentExperienceStatus[] = ["proposed", "confirmed", "rejected"];

function isoToMsOrNull(value: unknown): number | null {
  if (typeof value !== "string") return null;
  const ms = Date.parse(value);
  return Number.isNaN(ms) ? null : ms;
}

export function mapAgentExperienceEntry(raw: unknown): AgentExperienceEntry {
  if (typeof raw !== "object" || raw === null) {
    throw new HermesApiError("unexpected_error", "malformed agent_experience entry payload");
  }
  const r = raw as Record<string, unknown>;

  const id = r.id;
  if (typeof id !== "string" || id.length === 0) {
    throw new HermesApiError("unexpected_error", "missing agent_experience id");
  }
  const kind = r.kind;
  if (!(KINDS as readonly unknown[]).includes(kind)) {
    throw new HermesApiError("unexpected_error", `unknown agent_experience kind: ${String(kind)}`);
  }
  const status = r.status;
  if (!(STATUSES as readonly unknown[]).includes(status)) {
    throw new HermesApiError("unexpected_error", `unknown agent_experience status: ${String(status)}`);
  }
  const createdAt = isoToMsOrNull(r.created_at);
  if (createdAt === null) {
    throw new HermesApiError("unexpected_error", "malformed agent_experience created_at");
  }

  return {
    id,
    kind: kind as AgentExperienceKind,
    status: status as AgentExperienceStatus,
    content: typeof r.content === "string" ? r.content : "",
    source: typeof r.source === "string" ? r.source : "",
    proposerContext:
      r.proposer_context && typeof r.proposer_context === "object"
        ? (r.proposer_context as Record<string, unknown>)
        : null,
    deciderAccountId: typeof r.decider_account_id === "string" ? r.decider_account_id : null,
    decidedAt: isoToMsOrNull(r.decided_at),
    createdAt,
  };
}

export async function handleListAgentExperienceViaApi(
  client: HermesApiClient,
): Promise<Response> {
  try {
    const data = await client.dispatch("toee_agent_experience", "list_agent_experience", {});
    const entriesRaw =
      data && typeof data === "object" && Array.isArray((data as Record<string, unknown>).entries)
        ? ((data as Record<string, unknown>).entries as unknown[])
        : [];
    return json({ entries: entriesRaw.map(mapAgentExperienceEntry) });
  } catch (err) {
    return hermesErrorToProblem(err);
  }
}
