# Local username-password auth for Copilot Workbench MVP

The first-version **Copilot Workbench** uses self-managed username and password authentication instead of Google Workspace SSO or other external identity providers.

Each employee account is provisioned manually by a **Workbench Admin**, mapped to one workbench role (**Customer Service Rep**, **Workbench Supervisor**, or **Workbench Admin**). Password reset is handled through an admin-managed process in the first version; self-service forgot-password flows are optional later.

Access remains limited to employees who need **Follow-up Case** handling. The first version uses role gates only, not field-level masking.

**Considered options:** Google Workspace SSO (rejected—operator preference for local accounts); magic-link email login (rejected—not requested).
