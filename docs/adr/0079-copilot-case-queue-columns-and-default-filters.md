# Copilot Case Queue columns, default sort, and rep filters

The **Case Queue** zone on `/copilot` lists **Human Intervention Case** items for employee triage. It excludes **Contact Reason** `sales_outreach` cases per ADR-0050 and excludes **Auto-Handled Interaction** threads per ADR-0037.

## v1 columns

Each queue row shows, at minimum:

| Column | Purpose |
|--------|---------|
| Urgent flag | Marks **Urgent Follow-up Case** items |
| Channel | SMS, email, or voice channel for the case thread |
| Identity summary | Verified customer name, unmatched label, or non-customer organization hint |
| Contact Reason | Case routing label, including non-customer reasons |
| Last message preview | Short preview of the latest customer or Hermes turn |
| Case Assignee | Assigned **Workbench Account** or unassigned state |
| Status | Open, in progress, or resolved workbench state |
| Last activity time | Most recent customer, Hermes, or workbench activity timestamp |
| Tool failure flag | Visible when the case was created or escalated because of tool unavailability |

Rows do not expose full AR detail, invoice amounts, or cross-channel merged history in v1.

## Default sort

The queue sorts open cases as:

1. **Urgent Follow-up Case** items first
2. Unassigned cases before assigned cases within the same urgency tier
3. Oldest open case first by case-open time within each tier

Resolved cases are not shown in the default open queue.

## Default rep filter

**Customer Service Rep** users open `/copilot` with filters equivalent to:

- status = open or in progress
- assignee = mine or unassigned

Reps may widen filters manually, but the default view stays focused on their own workload plus the shared unassigned pool.

**Workbench Supervisor** and **Workbench Admin** users inherit the same default queue on `/copilot` and may apply broader filters, including **Agent Workload View**, without changing the v1 column set.

**Considered options:** sort by most recent customer activity after urgent (rejected—risks burying older unassigned cases); minimal columns without Contact Reason or tool-failure markers (rejected—weak triage for non-customer and tool-outage cases); configurable per-user columns in v1 (rejected—unnecessary UI complexity for launch).
