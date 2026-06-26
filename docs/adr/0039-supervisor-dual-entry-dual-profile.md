# Dual workbench entry with separate Copilot and Admin profiles for supervisors

**Workbench Supervisor** and **Workbench Admin** users may hold both operational and governance duties, but Hermes keeps those duties on separate profiles and separate workbench entry points in v1.

**Copilot Workbench entry** uses the **Internal Copilot Profile**. Supervisors use the same split layout as **Customer Service Rep** users: **Operations Dashboard** on the left and **Copilot Gateway** on the right. This entry supports **Human Intervention Case** handling, drafting, assignment, and the read-only **Auto-Handled Audit View**.

**Admin governance entry** uses the **Supervisor Admin Profile**. This entry supports **KnowledgeOps**, **Launch Eval Gate** review, **Workbench Account** administration, and related governance actions. It does not expose customer-facing send tools or live external-service customer-read tools.

A supervisor may use both entries in the same day, but not as one merged tool surface. Role checks determine which entry and profile are active for a session. Actions are attributed through **Workbench Audit Log** entries with the active profile context.

**Customer Service Rep** users receive only the Copilot Workbench entry in v1.

**Considered options:** merge Copilot and Admin tools into one supervisor profile (rejected—blurs customer-service and governance permissions); restrict supervisors to Admin only (rejected—supervisors must handle urgent cases and queue oversight); give reps access to Admin governance (rejected—knowledge and account control stay supervisor/admin only).
