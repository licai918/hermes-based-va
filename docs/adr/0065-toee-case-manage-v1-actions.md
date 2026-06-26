# toee_case_manage v1 actions for internal Copilot workflow

The **Internal Copilot Profile** uses `toee_case_manage` with five v1 **Domain Adapter Tool Action** values:

| Action | Purpose |
|--------|---------|
| `claim_case` | Set the signed-in **Workbench Account** as **Case Assignee** |
| `assign_case` | Set or change **Case Assignee** to another authorized workbench user |
| `update_priority` | Change case priority, including manual urgent promotion |
| `update_contact_reason` | Recategorize **Contact Reason** after employee review |
| `resolve_case` | Mark **Case Resolution** with a resolution summary |

All actions write **Workbench Audit Log** entries with actor, timestamp, case id, and changed fields. `toee_case_manage` does not create new external cases; creation remains on external `toee_case`.

Supervisor-only restrictions such as `assign_case` are enforced in **Tool Gate** by workbench role, not by registering a separate tool.

**Considered options:** merge priority, assignee, and contact-reason updates into one `update_case` action (rejected—weaker audit and role checks); omit employee contact-reason edits (rejected—conflicts with non-customer fallback workflow); allow Copilot to create cases directly (rejected—external `toee_case` owns creation).
