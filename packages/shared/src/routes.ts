import { HERMES_PROFILES, type HermesProfileId } from "./profiles";

export const ROUTES = {
  login: "/login",
  copilot: "/copilot",
  copilotSimulator: "/copilot/simulator",
  copilotAuditAutoHandled: "/copilot/audit/auto-handled",
  copilotAuditSalesOutreach: "/copilot/audit/sales-outreach",
  adminKnowledge: "/admin/knowledge",
  adminEval: "/admin/eval",
  adminAccounts: "/admin/accounts",
  adminMemoryAudit: "/admin/memory-audit",
  // L6 Agent-experience minimal admin list (0.0.3 S22, FR-23).
  adminAgentExperience: "/admin/agent-experience",
  // Aggregate-metrics admin panel (0.0.3 S26, FR-28).
  adminMetrics: "/admin/metrics",
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
