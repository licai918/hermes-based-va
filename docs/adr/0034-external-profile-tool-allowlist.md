# External Customer Service Profile tool allowlist for Text-First Launch

The **External Customer Service Profile** uses a default-deny **Profile Tool Allowlist**. **Domain Adapter Tools** register through the same native Hermes Tools API as **Hermes Built-in Tools** and are exposed only when this profile enables them.

**Allowed Domain Adapter Tools (v1):**

| Tool | Purpose |
|------|---------|
| `toee_knowledge_search` | Search **Public Site Knowledge** and published **Operational Policy Knowledge** |
| `toee_shopify_read` | Read orders, customers, products, and **Product Media Reply** sources |
| `toee_qbo_read` | Read invoices and AR status with email-link gating inside the tool |
| `toee_easyroutes_read` | Read delivery and route status |
| `toee_square_payment_link` | Send **Payment Link** only |
| `toee_textline_reply` | Reply in the current Textline **SMS Session** |
| `toee_case` | Create or update **Follow-up Case** records and urgency |
| `toee_identity_lookup` | Resolve **Phone Match Verification** and email-link readiness |
| `toee_customer_memory` | Upsert explicit customer preference slots |

**Allowed Hermes Built-in Tools (restricted):**

- `web_search` and `web_extract` only, for gaps not covered by knowledge search or business reads
- `browser_*`, full browser toolsets, and unconstrained live browsing are not enabled on this profile

**Not registered on this profile:**

- Business write tools for Shopify, QBO, Square, or EasyRoutes
- Copilot, KnowledgeOps, Workbench, or supervisor administration tools
- `terminal`, writable `file`, `code_execution`, `cronjob`, `skill_manage`, `delegate_task`, and similar system tools
- Outbound campaign tools (deferred past Text-First Launch)

**Enforcement order:** unavailable tools are not registered for the profile first; allowed tools still apply **Tool Gate** checks inside adapter code second; **Skill Guidance** and eval tests are supporting layers only.

**External profile preload:** this profile preloads a small Toee Tire policy Skill bundle at session start. Preload does not add tools beyond the allowlist.

**Considered options:** expose Hermes full `hermes-cli` toolset to external customers (rejected—terminal and file access); rely on Tool Gate without shrinking the allowlist (rejected—dangerous tools would remain callable); implement Shopify/QBO only via Skills without Domain Adapter Tools (rejected—no programmatic enforcement).
