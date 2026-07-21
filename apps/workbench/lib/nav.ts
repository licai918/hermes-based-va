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
];

export function navItemsForRole(role: WorkbenchRoleId): NavItem[] {
  if (role === WORKBENCH_ROLES.supervisor || role === WORKBENCH_ROLES.admin) {
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
