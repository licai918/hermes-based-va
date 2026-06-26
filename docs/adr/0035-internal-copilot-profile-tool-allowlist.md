# Internal Copilot Profile tool allowlist with phased write path

The **Internal Copilot Profile** uses its own default-deny **Profile Tool Allowlist** for **Copilot Gateway** sessions in the first version. It is broader than the **External Customer Service Profile**, but still excludes business-system writes.

**Allowed in v1 (in addition to external read tools):**

| Tool | Purpose |
|------|---------|
| Inherited external reads | `toee_knowledge_search`, `toee_shopify_read`, `toee_qbo_read`, `toee_easyroutes_read`, `toee_identity_lookup` |
| `toee_case_manage` | Claim, assign, update priority, and mark **Case Resolution** metadata in **Hermes Native Memory** |
| `toee_copilot_draft` | Draft SMS, email, or internal notes for employee review |
| `toee_workbench_read` | Read case thread summaries, tool-failure evidence, and **Workbench Audit Log** entries |
| `toee_customer_memory` | Upsert, clear, or verify **Customer Memory** preference slots inside an active case workflow |

**Restricted Hermes Built-in Tools:** same as external profile for customer-facing browsing — `web_search` and `web_extract` only when needed for investigation; no `browser_*`, `terminal`, writable `file`, `code_execution`, `cronjob`, or `skill_manage`.

**Not registered in v1:**

- Shopify, QBO, Square, or EasyRoutes write tools
- `toee_square_payment_link` and `toee_textline_reply` for autonomous customer sends
- Supervisor knowledge publish, campaign, or admin configuration tools
- Delegation and system execution tools

**v1 principle:** Copilot may explain, draft, and update case workflow inside Hermes, but accounting, payment, and customer outbound actions remain human-executed in source systems or through explicitly gated future tools.

**Future phased write path (post-v1, user-requested):**

Phase 1 **Copilot Governed Write** is employee-confirmed Textline send from a **Copilot Draft Action** inside an active **Human Intervention Case** only. **Auto-Handled Interaction** threads remain audit-only and do not use Copilot send.

Later phases may add additional **Copilot Governed Write** tools that remain on the same Hermes tool surface but require explicit employee confirmation, role checks, and **Tool Gate** rules before execution. Candidate future capabilities include:

- employee-confirmed Textline send from a Copilot draft
- low-risk Shopify note or tag updates after Rep confirmation
- supervisor-approved operational actions with full **Workbench Audit Log** attribution

Future writes must not bypass **Tool Gate**, profile allowlists, or **Launch Eval Gate** re-runs. High-risk actions such as refunds, accounting adjustments, discounts, and payment-link creation stay supervisor-governed or source-system manual until separately approved by ADR.

**Considered options:** give Copilot full external write tools in v1 (rejected—too much autonomous customer impact); keep Copilot read-only forever (rejected—user wants phased writes later); separate Copilot agent core (rejected—same **Hermes Core** with different profile allowlist).
