# Supervisor Admin Profile tool allowlist for governance-only access

The **Supervisor Admin Profile** uses a governance-focused **Profile Tool Allowlist**. It manages knowledge, quality, and workbench administration, but does not directly serve customers.

**Allowed Domain Adapter Tools (v1):**

| Tool | Purpose |
|------|---------|
| `toee_knowledge_ops` | Publish, roll back, and manage **Operational Policy Knowledge** and **KnowledgeOps** workflow, including completing **Knowledge Gap Prompt** slots |
| `toee_eval_review` | Review and sign off **Launch Eval Gate** results |
| `toee_workbench_admin` | Manage **Workbench Account** access and workbench configuration |
| `toee_workbench_read` | Read case statistics, audit evidence, and workbench operational state |
| `toee_knowledge_search` | Read approved knowledge for review before publish |

**Allowed views:** **Workbench Supervisor** capabilities including the read-only **Auto-Handled Audit View** for quality sampling.

**Restricted Hermes Built-in Tools:** `web_search` and `web_extract` only for policy or eval investigation when needed; no `browser_*`, `terminal`, writable `file`, `code_execution`, `cronjob`, or `skill_manage`.

**Not registered in v1:**

- Customer-facing send tools such as `toee_textline_reply` and `toee_square_payment_link`
- External-service read tools used for live customer answers (`toee_shopify_read`, `toee_qbo_read`, `toee_easyroutes_read`) except where needed indirectly through read-only workbench reporting already covered by `toee_workbench_read`
- Business write tools for Shopify, QBO, Square, or EasyRoutes
- **Copilot Draft Action** and **Copilot Governed Write** customer-send paths
- Outbound campaign tools (deferred past Text-First Launch)

**Principle:** **Supervisor Admin Profile** users govern knowledge, quality, and accounts. Customer conversations are handled by the **External Customer Service Profile** or by employees through **Human Intervention Case** workflows in the **Internal Copilot Profile**.

**Considered options:** give supervisors the same external toolset for emergency customer replies (rejected for v1—blurs governance and service roles); block audit view from Admin profile (rejected—supervisors need auto-handled sampling per ADR-0037); allow knowledge publish without eval linkage (rejected—Launch Eval Gate remains required).
