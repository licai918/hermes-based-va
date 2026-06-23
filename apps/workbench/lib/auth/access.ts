// Route-derived role gating (ADR-0093 route-prefix profiles, ADR-0077/0037 audit
// = supervisor/admin only, ADR-0078/0011 admin = supervisor/admin only). Pure and
// EDGE-SAFE: imports only from @toee/shared, no Node-only APIs.
import {
  profileForApiPrefix,
  WORKBENCH_ROLES,
  type WorkbenchRoleId,
} from "@toee/shared";

// Re-export so callers can derive the Hermes profile from a path in one place.
export { profileForApiPrefix };

function isAuditPath(pathname: string): boolean {
  return (
    pathname.startsWith("/copilot/audit") ||
    pathname.startsWith("/api/copilot/audit")
  );
}

function isAdminPath(pathname: string): boolean {
  return pathname.startsWith("/admin") || pathname.startsWith("/api/admin");
}

export function requiresSupervisorOrAdmin(pathname: string): boolean {
  return isAuditPath(pathname) || isAdminPath(pathname);
}

export function canAccess(role: WorkbenchRoleId, pathname: string): boolean {
  if (requiresSupervisorOrAdmin(pathname)) {
    return (
      role === WORKBENCH_ROLES.supervisor || role === WORKBENCH_ROLES.admin
    );
  }
  return true;
}
