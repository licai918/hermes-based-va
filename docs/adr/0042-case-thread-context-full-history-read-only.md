# Full customer thread context when handling human-intervention cases

When an employee opens a **Human Intervention Case** in the **Copilot Workbench**, the **Operations Dashboard** shows the full **Customer Thread** history for that Textline phone number as read-only context. The view includes prior **Auto-Handled Interaction** turns, earlier **SMS Session** windows, and the active case segment.

The active **Human Intervention Case** is visually highlighted in the thread. Employees may read the full history to draft replies and avoid repeating questions, but they cannot edit, delete, or rewrite prior customer or Hermes messages from the thread panel.

This case-context thread view is available to **Customer Service Rep**, **Workbench Supervisor**, and **Workbench Admin** users through the **Copilot Workbench** entry on the **Internal Copilot Profile**. It is not a separate work queue and does not change the rule that only **Human Intervention Case** items enter the default queue.

Opening or refreshing case thread context writes a **Workbench Audit Log** entry recording the viewer, timestamp, case identifier, and customer thread identifier.

The read-only **Auto-Handled Audit View** remains a separate supervisor-facing browse surface for quality sampling without an open case. Reps do not receive that standalone audit view in v1, but they do receive inline full-thread context while handling an assigned or selected **Human Intervention Case**.

**Considered options:** show only the case-triggering message fragment (rejected—reps lose needed context); grant reps the standalone **Auto-Handled Audit View** (rejected—adds queue noise and duplicates case-context access); allow supervisors only to see full thread during case work (rejected—reps need the same context to resolve cases).
