# toee_case v1 actions for external follow-up case creation

The **External Customer Service Profile** uses `toee_case` with two v1 **Domain Adapter Tool Action** values:

| Action | Purpose | Allowed fields |
|--------|---------|----------------|
| `create_case` | Open a **Follow-up Case** from external service traffic | `contact_reason`, `summary`, `channel_thread_id`, initial `urgency` |
| `update_case` | Adjust an existing open external case when classification or urgency changes | `urgency`, `contact_reason` only |

`create_case` may set default urgency from non-customer playbooks, such as government traffic marked **Urgent Follow-up Case**. `update_case` supports **Contact Reason Uplift** and post-clarification contact-reason changes without creating duplicate cases.

External `toee_case` does not assign **Case Assignee**, mark **Case Resolution**, or write internal workbench notes. Those operations belong to `toee_case_manage` on the **Internal Copilot Profile**.

**Considered options:** `create_case` only with all urgency and reason changes handled outside agent tools (rejected—agent needs governed uplift updates); split `set_urgency` and `set_contact_reason` into separate actions (rejected—unnecessary surface area for v1); let external profile resolve or assign cases (rejected—Copilot workflow only).
