# Multi-user Copilot workbench with assignment and audit

> **Storage substrate superseded by ADR-0140/0142.** Per-account attribution,
> claim/assign/reassign, **Case Resolution**, and the audit event list all still hold.
> Superseded: the substrate — **Workbench Audit Log** entries write to the **Toee Business
> Datastore** (Postgres, L3), not **Hermes Native Memory** — and the "breaks Hermes-native
> memory goal" rejection rationale, which no longer describes the goal.
> Current direction → [`docs/architecture/memory-layers.md`](../architecture/memory-layers.md).

Each human employee uses their own **Workbench Account** to sign in to the **Copilot Workbench**. Case handling is attributed per person, not shared anonymously.

**Case Assignee** tracks who owns or is actively handling a **Follow-up Case**. Employees may claim, be assigned, or reassign cases. **Case Resolution** records the resolving **Workbench Account**.

The **Operations Dashboard** supports an **Agent Workload View** so supervisors can see which cases each human agent handled, is handling, or resolved. **Customer Service Rep** users see their own assigned cases and the shared unassigned queue by default.

Every significant workbench action writes a **Workbench Audit Log** entry in **Hermes Native Memory**, including at minimum: login, case view/open, assignment/claim, Copilot draft generation, status change, and resolution. Logs record actor, timestamp, case id, and action type for accountability.

**Considered options:** shared team inbox without per-user attribution (rejected—no accountability); audit only in external spreadsheets (rejected—breaks Hermes-native memory goal).
