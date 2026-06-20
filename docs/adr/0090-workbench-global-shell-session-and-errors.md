# Workbench global shell for session, logout, and errors

The authenticated workbench application shared by **Copilot Workbench** and **Admin Governance Console** uses a minimal global shell in v1.

## Top bar and user menu

The top bar shows role-aware primary navigation per ADR-0084. The right side exposes a user menu with:

- signed-in username
- current workbench role
- **Logout** action

Logout ends the active workbench session and returns the user to the login page.

## Session timeout behavior

Workbench sessions follow the 8-hour inactivity timeout from ADR-0018.

When inactivity timeout is reached:

1. Hermes shows a warning modal that the session expired
2. the app signs the user out
3. the user is redirected to the login page

Re-authentication is required before returning to `/copilot` or `/admin/*` routes.

## Global error banner

When a workbench API call or **Domain Adapter Tool** request fails in a way that blocks the current page action, the app shows a dismissible global error banner below the top bar.

The banner contains a short English operator-facing message and an error class or reference when available. Page-local empty states and read-only views remain usable when the failure does not block the whole page.

## Page-local empty states

v1 does not define a separate design-system pass for every empty state. Each route keeps its own empty copy and layout, including:

- `/copilot` with no open cases
- `/copilot` with no selected case in **Copilot Gateway**
- audit lists with no records
- `/admin/knowledge` slots with `Empty` or `Gap` status
- `/admin/eval` with no runs yet
- `/admin/accounts` with no provisioned users

**Considered options:** logout only with all other shell behavior deferred (rejected—session timeout and operator-visible failures are security and operations requirements); add notifications center and theme switching in v1 (rejected—unnecessary for launch scope); one generic empty-state component without route-specific copy (rejected—weaker orientation for case, audit, and governance pages).
