// Role-aware top navigation (ADR-0084). Reps see only Copilot; supervisors and
// admins additionally see the three Admin Governance Console entries. Audit
// routes are reached from Copilot-side navigation, not the top bar. Pure +
// Edge-safe so it can be shared by the server shell and any client nav.
import { ROUTES, WORKBENCH_ROLES, type WorkbenchRoleId } from "@toee/shared";

export type NavItem = { label: string; href: string };

const COPILOT: NavItem = { label: "Copilot", href: ROUTES.copilot };
// Conversation Simulator (FR-8, 0.0.3 S03): same copilot group/profile as
// COPILOT above, open to every signed-in role -- canAccess only gates audit
// and admin paths, and /copilot/simulator is neither.
const SIMULATOR: NavItem = { label: "Simulator", href: ROUTES.copilotSimulator };
const GOVERNANCE: NavItem[] = [
  { label: "Knowledge", href: ROUTES.adminKnowledge },
  { label: "Eval", href: ROUTES.adminEval },
  { label: "Accounts", href: ROUTES.adminAccounts },
  // FR-20 (0.0.3 S20): supervisor memory audit view -- slots + write history +
  // attributed clear.
  { label: "Memory Audit", href: ROUTES.adminMemoryAudit },
  // FR-23 (0.0.3 S22): L6 Agent-experience minimal admin list.
  { label: "Agent Experience", href: ROUTES.adminAgentExperience },
  // FR-28 (0.0.3 S26): aggregate-metrics admin panel.
  { label: "Metrics", href: ROUTES.adminMetrics },
];

// FR-23 (0.0.4 S15): integrations status page. ADMIN-ONLY (a credential surface,
// canAccess -> requiresAdmin), so it is NOT in the supervisor+admin GOVERNANCE list
// above -- a supervisor must not see a link that 403s.
const ADMIN_ONLY: NavItem[] = [
  { label: "Integrations", href: ROUTES.adminIntegrations },
];

export function navItemsForRole(role: WorkbenchRoleId): NavItem[] {
  if (role === WORKBENCH_ROLES.admin) {
    return [COPILOT, SIMULATOR, ...GOVERNANCE, ...ADMIN_ONLY];
  }
  if (role === WORKBENCH_ROLES.supervisor) {
    return [COPILOT, SIMULATOR, ...GOVERNANCE];
  }
  return [COPILOT, SIMULATOR];
}

const ROLE_LABELS: Record<WorkbenchRoleId, string> = {
  [WORKBENCH_ROLES.rep]: "Customer Service Rep",
  [WORKBENCH_ROLES.supervisor]: "Workbench Supervisor",
  [WORKBENCH_ROLES.admin]: "Workbench Admin",
};

export function roleLabel(role: WorkbenchRoleId): string {
  return ROLE_LABELS[role];
}
