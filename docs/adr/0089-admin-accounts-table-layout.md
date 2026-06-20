# Admin accounts table layout with drawer actions

The `/admin/accounts` route on the **Admin Governance Console** uses the **Supervisor Admin Profile** and `toee_workbench_admin` per ADR-0078.

## Table-first layout

The page uses a table-first layout rather than master-detail because account records are row-centric and do not contain long-form policy content.

The main table shows, at minimum:

| Column | Purpose |
|--------|---------|
| Username | **Workbench Account** login identifier |
| Role | `Customer Service Rep`, `Workbench Supervisor`, or `Workbench Admin` |
| Status | `Active` or `Disabled` |
| Last login | Most recent successful sign-in timestamp when available |
| Created time | Account provisioning timestamp |

A top-level **Create Account** button opens a drawer or modal form.

## Row and create actions

Account administration actions use drawer or modal forms plus confirmation dialogs:

| Action | UI pattern |
|--------|------------|
| Create Account | drawer or modal with username, initial role, and initial password fields |
| Edit Role | drawer or modal to change role assignment |
| Disable Account | confirmation dialog before `disable_account` |

v1 does not provide self-service forgot-password flows. The accounts page may show an admin-only note that password reset is handled manually by **Workbench Admin** users per ADR-0017.

Disabled accounts cannot sign in. The accounts page does not expose customer-case, knowledge, or eval actions.

**Considered options:** master-detail account layout like `/admin/knowledge` (rejected—unnecessary for short account records); inline editable table rows (rejected—too easy to mis-click role changes); self-service password reset on the same page in v1 (rejected—deferred by ADR-0017).
