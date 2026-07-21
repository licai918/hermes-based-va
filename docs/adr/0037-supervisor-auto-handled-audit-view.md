# Supervisor read-only audit view for auto-handled interactions

> **Storage substrate superseded by ADR-0140/0142.** The supervisor read-only
> **Auto-Handled Audit View** is unchanged. Only the substrate changes: the view reads
> conversation, tool-call, and outcome records from the **Toee Business Datastore**
> (Postgres), not **Hermes Native Memory**, which is conversation-only.
> Current direction → [`docs/architecture/memory-layers.md`](../architecture/memory-layers.md).

The default **Copilot Workbench** queue shows only **Human Intervention Case** items for **Customer Service Rep** users. **Auto-Handled Interaction** threads do not enter that work queue and do not require Copilot drafting in v1.

**Workbench Supervisor** and **Workbench Admin** users may open a separate read-only **Auto-Handled Audit View** to review completed external interactions for quality sampling and compliance checks. This view reads conversation, tool-call, and outcome records from **Hermes Native Memory** and audit logs.

The audit view is browse and inspect only. It does not allow drafting, Textline send, case assignment, Payment Link actions, or business-system writes. **Customer Service Rep** users do not receive this view in the first version.

Opening a specific auto-handled thread in the audit view writes a **Workbench Audit Log** entry recording the viewer, timestamp, and thread identifier.

**Considered options:** hide auto-handled threads entirely from the workbench UI (rejected—supervisors cannot sample quality); mix auto-handled and human cases in the default rep queue (rejected—creates noise and conflicts with human-intervention-only Copilot workflow); grant audit view to all reps in v1 (rejected—unnecessary queue distraction).
