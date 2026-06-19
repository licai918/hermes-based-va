import { HERMES_PROFILES, type HermesProfileId } from "./profiles";

export const ROUTES = {
  login: "/login",
  copilot: "/copilot",
  copilotAuditAutoHandled: "/copilot/audit/auto-handled",
  copilotAuditSalesOutreach: "/copilot/audit/sales-outreach",
  adminKnowledge: "/admin/knowledge",
  adminEval: "/admin/eval",
  adminAccounts: "/admin/accounts",
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
