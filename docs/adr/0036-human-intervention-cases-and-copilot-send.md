# Human-intervention cases only for Copilot; auto-handled interactions audit-only

> **Storage substrate superseded by ADR-0140/0142.** The **Auto-Handled Interaction** vs
> **Human Intervention Case** split and the phase-1 governed-write rule still hold. Only
> the substrate changes: **Auto-Handled Interaction** conversation, tool-call, and outcome
> records go to the **Toee Business Datastore** (Postgres), not **Hermes Native Memory**,
> which is conversation-only.
> Current direction → [`docs/architecture/memory-layers.md`](../architecture/memory-layers.md).

Not every customer interaction enters the **Copilot Workbench** queue. When the **External Customer Service Profile** completes a request within policy, Hermes records the interaction for audit and does not open a human workflow in Copilot.

**Auto-Handled Interaction:** an external customer-service turn that Hermes completes without creating a **Follow-up Case**. Hermes still writes conversation, tool-call, and outcome records to **Hermes Native Memory** and audit logs for traceability. These interactions are reviewable for compliance and quality, but they do not require **Copilot Draft Action** or employee send in v1.

**Human Intervention Case:** a **Follow-up Case** or equivalent case record explicitly marked as requiring employee review. Only these cases appear in the default **Operations Dashboard** work queue and use **Copilot Gateway** for drafting and later governed actions.

**Copilot v1 behavior:** employees use Copilot only for **Human Intervention Case** items. Hermes does not expect human review for **Auto-Handled Interaction** threads beyond audit access.

**Copilot Governed Write phase 1 (confirmed):** the first post-v1 governed write is employee-confirmed Textline send from a **Copilot Draft Action**, and only within an active **Human Intervention Case** tied to the current customer thread. The send must attribute the acting **Workbench Account**, pass **Tool Gate** checks, and write **Workbench Audit Log** entries. Hermes does not allow Copilot to originate new customer threads from unrelated cases.

**Later governed-write phases** remain separate ADR decisions. Refunds, accounting adjustments, discounts, and autonomous Payment Link creation stay outside Copilot until explicitly approved.

**Considered options:** route every external SMS thread through Copilot for human review (rejected—defeats 24/7 auto-service); keep no audit record for auto-handled turns (rejected—compliance and eval need traceability); allow Copilot to send Textline without case linkage (rejected—weak accountability).
