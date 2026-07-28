import { HERMES_PROFILES, type HermesProfileId } from "./profiles";

export const ROUTES = {
  login: "/login",
  copilot: "/copilot",
  copilotSimulator: "/copilot/simulator",
  copilotAuditAutoHandled: "/copilot/audit/auto-handled",
  copilotAuditSalesOutreach: "/copilot/audit/sales-outreach",
  // Memory Hub (0.0.5 S14, FR-21): the L1-L7 layer map with live counts. Sits
  // ABOVE the per-layer consoles -- an entry point, never a replacement, so every
  // deep link below still works.
  adminMemoryHub: "/admin/memory-hub",
  // Unified review inbox (0.0.5 S15, FR-22): ONE queue over the L6 and L7
  // proposal tables plus the `review_item` store, with Accept/Reject and
  // Re-classify. The per-layer consoles below stay -- they are where a decided
  // entry's history is read; this is where a pending one is decided.
  adminInbox: "/admin/inbox",
  adminKnowledge: "/admin/knowledge",
  adminEval: "/admin/eval",
  adminAccounts: "/admin/accounts",
  adminMemoryAudit: "/admin/memory-audit",
  // L6 Agent-experience minimal admin list (0.0.3 S22, FR-23).
  adminAgentExperience: "/admin/agent-experience",
  // L7 Semantic Lexicon console (0.0.5 S02, FR-3/FR-8): the human gate over the
  // domain language -- approve/edit/reject/retire plus manual add.
  adminLexicon: "/admin/lexicon",
  // Aggregate-metrics admin panel (0.0.3 S26, FR-28).
  adminMetrics: "/admin/metrics",
  // Integrations status page (0.0.4 S15, FR-23). Admin-ONLY (a credential
  // surface), deliberately narrower than the rest of /admin/* -- see
  // lib/auth/access.ts.
  adminIntegrations: "/admin/integrations",
} as const;

export function profileForApiPrefix(
  pathname: string,
): HermesProfileId | null {
  if (pathname.startsWith("/api/copilot") || pathname.startsWith("/copilot")) {
    return HERMES_PROFILES.internalCopilot;
  }

  if (pathname.startsWith("/api/admin") || pathname.startsWith("/admin")) {
    return HERMES_PROFILES.supervisorAdmin;
  }

  return null;
}
