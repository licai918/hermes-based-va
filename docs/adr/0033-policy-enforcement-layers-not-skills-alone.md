# Policy enforcement through tools and profiles, not Skills alone

> **Examples superseded (2026-07-20).** The decision stands in full: the five-layer
> enforcement stack, and Skills are not a security boundary. Only the examples under
> **Scheduled jobs vs conversational agents** are stale — there is no weekly **Shopify
> Knowledge Sync** or **Tavily Gap Crawl** rebuild Skill. The distinction itself holds.
> Current direction → [`docs/architecture/memory-layers.md`](../architecture/memory-layers.md).

Toee Tire policy boundaries such as **Product Media Reply**, **Payment Link**, zero disclosure for **Unmatched Caller**, and accounting read limits must not rely on Skills as the only enforcement mechanism.

Hermes **Skills** are procedural markdown guidance loaded on demand through `skills_list` and `skill_view`. The model may skip, delay, or misapply a Skill. Skills are appropriate for playbooks, scheduled job procedures, and operator workflows, but they are not a hard security or compliance boundary for customer-facing actions.

**Enforcement layers (required stack):**

1. **Hermes Profile** — each profile carries system prompt boundaries (`SOUL.md`, profile config), allowed toolsets, and knowledge scope. The **External Customer Service Profile** must not expose internal or write tools. Native tool allowlists come from profile toolsets and per-tool disable settings in `config.yaml`.

2. **Tool Gate** — not a separate Hermes core module. Toee Tire implements policy checks inside **Domain Adapter** Tools and the **Channel Gateway** using the native Hermes Tools/plugin extension surface. Examples: Payment Link requires **Verified Customer**; product media price/inventory requires verification; QBO reads require email link success.

3. **Skill Guidance** — Toee Tire Skills document procedures for agents and scheduled jobs, but duplicate critical rules already enforced by Tool Gates.

4. **Launch Eval Gate** — regression suite catches model drift when prompts, models, or knowledge change.

5. **Audit log** — tool calls and workbench actions remain attributable for post-hoc review.

**Scheduled jobs vs conversational agents:** weekly **Shopify Knowledge Sync**, **Tavily Gap Crawl**, and similar rebuild Skills run as deterministic scheduled tasks with fixed inputs. Their risk is operational failure, not LLM disobedience. Customer SMS/voice sessions are conversational and require Tool Gates.

**External profile preload:** the **External Customer Service Profile** should preload a small Toee Tire policy Skill bundle at session start so guidance is present early, but preload does not replace Tool Gates.

**Considered options:** Skills-only policy enforcement (rejected—model may not load or follow them); custom Hermes core fork for every rule (rejected—conflicts with Hermes-native goal); prompt-only boundaries without tool checks (rejected—insufficient for accounting and payment rules).
