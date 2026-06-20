# Copilot Operations Dashboard dual-zone layout with audit routes

The first-version **Copilot Workbench** default route is `/copilot` on the **Internal Copilot Profile**. It keeps the split layout from ADR-0028: **Operations Dashboard** on the left and **Copilot Gateway** on the right.

The left **Operations Dashboard** uses a dual-zone layout on the default route:

- **Case Queue zone** — the primary **Human Intervention Case** list with urgency, filters, **Case Assignee**, and resolution status
- **Case Thread Context zone** — read-only full channel thread history for the selected case, including prior **Auto-Handled Interaction** turns on that channel

Selecting a case in the queue loads **Case Thread Context** in the lower or secondary left zone and scopes the right-side **Copilot Gateway** to that case. Clearing selection collapses or empties the thread zone.

**Workbench Supervisor** and **Workbench Admin** users receive additional read-only audit routes under the same Copilot entry:

- `/copilot/audit/auto-handled` — **Auto-Handled Audit View**
- `/copilot/audit/sales-outreach` — **Sales Outreach Audit View**

These audit routes are not tabs on the default rep queue page. **Customer Service Rep** users do not receive navigation to them in v1.

Audit routes are browse and inspect only. They do not expose drafting, Textline send, case assignment, or business-system writes. Opening a specific audit record writes a **Workbench Audit Log** entry per ADR-0037 and ADR-0050.

**Considered options:** three peer tabs for queue and both audit views on one page (rejected—adds noise to the rep default surface); single-column mixed queue and thread scroll (rejected—weak case-selection workflow); place audit views in the **Admin Governance Console** (rejected—audit sampling is operational quality work and stays on the Copilot entry per ADR-0039).
