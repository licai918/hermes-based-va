# Copilot Gateway interaction states by route and case selection

The **Copilot Gateway** stays on the right side of the split layout for operational case work on `/copilot`, but its enabled state depends on route and selected case context.

## `/copilot` with no case selected

When an employee opens `/copilot` or clears the current case selection, the right pane shows an idle **Copilot Gateway** state. It prompts the user to select a **Human Intervention Case** from the **Case Queue**.

In this state the gateway does not load case or customer-thread context and does not allow **Copilot Draft Action** generation. Employees may still use queue filters and browse the case list on the left.

## `/copilot` with a case selected

When an employee selects a **Human Intervention Case**, the left **Case Thread Context** zone loads the read-only full channel thread and the right **Copilot Gateway** scopes to that case.

In this state employees may use v1 **Copilot Draft Action** capabilities (`draft_sms`, `draft_email`, `draft_internal_note`) and inspect tool evidence for the active case. Governed customer send remains limited to later employee-confirmed Textline send inside an active case per ADR-0036.

## Audit routes hide the gateway

On `/copilot/audit/auto-handled` and `/copilot/audit/sales-outreach`, the layout removes the right **Copilot Gateway** pane entirely. The audit list and record detail use the full workbench width as read-only browse surfaces.

Audit routes do not allow drafting, Textline send, case assignment, or business-system writes per ADR-0037 and ADR-0050.

**Considered options:** keep the gateway visible on audit routes for internal-note drafting only (rejected—blurs read-only audit boundaries); hide the gateway until a case is selected by collapsing the right pane (rejected—weaker orientation on first load); allow Copilot drafting without a selected case (rejected—conflicts with human-intervention-only workflow).
