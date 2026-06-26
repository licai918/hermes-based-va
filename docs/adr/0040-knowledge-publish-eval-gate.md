# Operational policy publish requires eval pass before external use

**Operational Policy Knowledge** does not become customer-effective immediately when a supervisor submits it in **KnowledgeOps**. A **Knowledge Publish Eval Gate** must pass before the new version is served to the **External Customer Service Profile**.

When a **Required Operational Policy Slot** or other governed operational policy text moves toward publish, Hermes stores it as **Pending Eval Knowledge** until evaluation completes. If evaluation fails, the content stays unpublished for external use and the previous **Published Operational Policy** version remains active.

**Targeted evaluation:** a publish attempt runs at minimum the eval scenarios tied to the changed slot plus a required regression subset. Full launch eval is still required for initial Text-First go-live and for changes to primary or fallback models, external system prompts, or tool permissions.

**Pass behavior:** on pass, the new version becomes **Published Operational Policy** for external retrieval and is recorded with model slug, prompt version, and knowledge version for audit.

**Fail behavior:** on fail, Hermes keeps serving the prior published version externally. **Workbench Supervisor** may sign off only medium-severity failures per the **Launch Eval Gate** rules before promotion.

**Rollback:** supervisors may roll back to a prior published operational policy version in **KnowledgeOps** without creating a customer-facing gap. A rollback that changes customer-effective policy still requires eval pass before the rolled-back version becomes active again if it was not already the current published baseline.

**Considered options:** publish immediately on supervisor click (rejected—policy drift could reach customers before validation); require full 13-scenario eval on every typo fix (rejected—too slow; targeted eval is enough); supervisor manual sign-off without eval (rejected—user chose eval-gated publish).
