# Required operational policy slots with proactive gap filling

Before the **External Customer Service Profile** handles policy-bound customer scenarios, Hermes must define six **Required Operational Policy Slots** as part of **Operational Policy Knowledge**. Each slot must exist as a structured placeholder at onboarding time, even if content is not yet written.

The six required slots are:

1. Business hours and service boundaries (including after-hours limits)
2. Payment methods and Payment Link rules
3. Order and delivery inquiry guidance
4. Accounting inquiry guidance (including email-link failure handling)
5. Returns, exchanges, and stockout policy (operational interpretation layer)
6. Standard exception scripts (unmatched caller, ambiguous match, email link failure, urgent cases, standard non-customer inbound intake, and email support signature text)

Each slot requires an owner and review date when published through **KnowledgeOps**. Website crawl does not create or replace these slots.

If a slot has no approved content after onboarding or training, Hermes must issue a **Knowledge Gap Prompt** to authorized **Supervisor Admin Profile** users, asking targeted questions to fill that slot. Hermes must not invent operational policy from website marketing copy or model inference when a required slot is empty. For customers, empty slots mean safe fallback responses and **Follow-up Case** creation where appropriate—not improvised policy answers.

**Considered options:** allow go-live with only website RAG (rejected—misses Hermes-specific boundaries); silently skip empty slots (rejected—creates policy hallucination risk); require manual spreadsheet tracking outside Hermes (rejected—no proactive completion loop).
