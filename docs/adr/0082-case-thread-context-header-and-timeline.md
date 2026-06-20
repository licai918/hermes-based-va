# Case Thread Context header bar and read-only timeline layout

When an employee selects a **Human Intervention Case** on `/copilot`, the lower or secondary left zone loads **Case Thread Context** as a two-part panel.

## Sticky case header bar

The top of **Case Thread Context** is a fixed header bar with case metadata and workbench actions.

**Metadata row** shows, at minimum:

- channel
- identity summary
- editable **Contact Reason** selector
- urgent state
- current **Case Assignee**

**Action controls** on the same header bar include:

| Control | Who may use it |
|---------|----------------|
| `claim_case` | Any authorized Copilot user when the case is unassigned |
| `assign_case` | **Workbench Supervisor** and **Workbench Admin** users |
| `update_priority` | **Workbench Supervisor** and **Workbench Admin** users by default; reps may lower urgency only if separately enabled later |
| `resolve_case` | Any authorized Copilot user handling the case |

`update_contact_reason` uses the header **Contact Reason** selector rather than a separate action button. All `toee_case_manage` actions write **Workbench Audit Log** entries.

Case-management actions live in **Case Thread Context**, not in queue rows and not in the **Copilot Gateway** header.

## Read-only timeline body

Below the header bar, the panel shows the full active-channel thread history in chronological order. The view is read-only.

- prior **Auto-Handled Interaction** turns remain visible but visually de-emphasized
- the active **Human Intervention Case** segment is highlighted
- employees cannot edit historical customer or Hermes messages in v1

Opening or refreshing **Case Thread Context** writes a **Workbench Audit Log** entry per ADR-0042.

**Considered options:** inline queue-row actions only (rejected—resolve and contact-reason edits need full thread context); move claim and resolve actions to the **Copilot Gateway** header (rejected—splits operational case controls away from the thread employees are reading); hide auto-handled turns entirely (rejected—conflicts with full-history case context).
