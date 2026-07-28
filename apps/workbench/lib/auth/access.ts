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

// The integrations status page + its BFF are ADMIN-ONLY (0.0.4 S15, FR-23,
// gap-review P4): integrations are a CREDENTIAL surface, deliberately narrower
// than the rest of /admin/* (supervisor+admin, an OPERATIONS surface like the
// dead-letter view). A supervisor triaging stuck work needs the dead-letter view;
// only an admin should see the credential-configuration status of every backend.
//
// RULED, 0.0.5 S02 review: the L7 semantic lexicon (/admin/lexicon,
// /api/admin/lexicon) is deliberately NOT in this narrower tier, although its
// brief says "all admin-only". "Admin-only" there means "never LLM-callable" --
// the slice's Approach glosses it as `_AGENT_EXCLUDED_ACTIONS`, and that is
// enforced in the tool catalog, not here. As a human surface it is governance,
// exactly like its L6 sibling /admin/agent-experience, which is also
// supervisor+admin; a supervisor curating domain vocabulary is the same kind of
// act as a supervisor deciding an L6 proposal. Narrow it only if the L6 gate
// narrows too, or the two consoles will disagree about who governs memory.
function isAdminOnlyPath(pathname: string): boolean {
  return (
    pathname.startsWith("/admin/integrations") ||
    pathname.startsWith("/api/admin/integrations")
  );
}

export function requiresSupervisorOrAdmin(pathname: string): boolean {
  return isAuditPath(pathname) || isAdminPath(pathname);
}

export function requiresAdmin(pathname: string): boolean {
  return isAdminOnlyPath(pathname);
}

export function canAccess(role: WorkbenchRoleId, pathname: string): boolean {
  if (requiresAdmin(pathname)) {
    return role === WORKBENCH_ROLES.admin;
  }
  if (requiresSupervisorOrAdmin(pathname)) {
    return (
      role === WORKBENCH_ROLES.supervisor || role === WORKBENCH_ROLES.admin
    );
  }
  return true;
}
