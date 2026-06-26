# Workbench login landing and role-based top navigation

The first-version **Copilot Workbench** and **Admin Governance Console** share one authenticated workbench application with local username-password login per ADR-0017.

## Default landing route

Every authorized **Workbench Account** lands on `/copilot` immediately after successful login.

This includes **Customer Service Rep**, **Workbench Supervisor**, and **Workbench Admin** users. Supervisors and admins still handle urgent **Human Intervention Case** work from the operational queue, so the default landing stays on case triage rather than governance pages.

## Top navigation by role

**Customer Service Rep** users see one primary navigation entry:

- **Copilot** → `/copilot`

Reps do not receive links to `/admin/*` routes or audit-route navigation in v1.

**Workbench Supervisor** and **Workbench Admin** users see four top-level navigation entries:

| Nav label | Route |
|-----------|-------|
| Copilot | `/copilot` |
| Knowledge | `/admin/knowledge` |
| Eval | `/admin/eval` |
| Accounts | `/admin/accounts` |

Supervisor and admin users may also access read-only audit routes through Copilot-side navigation:

- `/copilot/audit/auto-handled`
- `/copilot/audit/sales-outreach`

Admin navigation switches the active session to the **Supervisor Admin Profile** context per ADR-0039. Copilot navigation uses the **Internal Copilot Profile** context. The app does not merge those tool surfaces into one page.

**Considered options:** route admins to `/admin/knowledge` by default (rejected—delays urgent case handling); remember last-used entry on login (rejected—adds state complexity for little launch benefit); show admin links to reps (rejected—violates governance access boundaries).
