# PRD: Hermes VA Text-First Launch (Textline SMS)

> **Superseded in part (2026-07-20) — read this first.** This PRD's *behaviour and scope* still
> hold, but its **substrate is wrong throughout**. ADR-0139 (Hermes is the Nous **Python** agent
> plugin — no TypeScript `Hermes Runtime Shim`, no `packages/hermes-runtime` boot path),
> ADR-0140 (**Postgres is the system of record**; Hermes Native Memory is conversation-only and
> entirely off in practice), ADR-0141 (workbench BFF reaches per-profile Hermes **over HTTP**,
> not in-process), ADR-0142 (local-first). Read every "Hermes Native Memory" and "Hermes Runtime
> Shim" reference below as the historical design.
> **Customer Memory — user stories 21–23 and delivery phase 4 — SHIPPED** in 0.0.1 (PR #54) and
> was hardened in 0.0.2 (PR #55); it is not pending work.
> Current memory map → [`docs/architecture/memory-layers.md`](../architecture/memory-layers.md).

## Problem Statement

Toee Tire needs governed AI customer service on an external channel without exposing accounting data, bypassing policy, or forcing customers through a separate verification product. The business wants to validate **Hermes Core**, **Tool Gate**, knowledge layers, employee **Copilot Workbench**, and quality gates on **Textline SMS** first because text is lower latency and easier to debug than voice.

Today the repository has domain decisions (CONTEXT, ADRs 0001–0138), **Launch Eval** YAML fixtures for `text_first_launch` and `email_go_live`, and minimal application scaffold. There is no runnable **Channel Gateway**, **Launch Eval Runner**, **Domain Adapter** implementation, or end-to-end SMS path. Text-First go-live is blocked until this implementation PRD is delivered.

## Solution

Deliver **Text-First Launch** on Textline SMS: a monorepo implementation where **services/hermes-gateway** receives verified Textline webhooks, normalizes **InboundChannelEvent** records, performs **Ingress Phone Match**, runs the **External Customer Service Profile** asynchronously, and sends governed SMS replies; **apps/workbench** gives employees **Copilot Workbench** and **Admin Governance Console** access through BFF routes backed by the same **Hermes Runtime Shim** and **Domain Adapter Tools**; **Launch Eval Runner** executes repository fixtures and blocks promotion on high-severity failures.

Integration backends start on **mock drivers** per ADR-0132. Composio Connected Account cutover is an integration milestone documented in the ops runbook, not a blocker for initial scaffold and eval-green delivery.

## User Stories

### External customers (SMS)

1. As a **Verified Customer** texting from a **Registered Phone**, I want Hermes to answer order, delivery, and invoice questions in one thread, so that I get account help without a verification ceremony.
2. As an **Unmatched Caller**, I want Hermes to refuse account-specific disclosure and open a **Follow-up Case**, so that my request is handled safely by staff.
3. As a caller with **Ambiguous Phone Match**, I want Hermes to ask for disambiguation such as order number, so that the wrong customer account is not used.
4. As a **Verified Customer** with **Email Link Failure**, I want Shopify order help but not wrongful QBO disclosure, so that cross-system identity rules are respected.
5. As a **Verified Customer**, I want a **Payment Link** only on my verified SMS thread, so that payment links are not sent to alternate numbers I mention in chat.
6. As any customer, I want refund, discount, and accounting adjustment requests refused with a **Follow-up Case**, so that Hermes does not promise unauthorized writes.
7. As any customer, I want Hermes to resist prompt injection and policy bypass attempts, so that tool permissions and disclosure rules hold.
8. As any customer, I want safe fallback when **Required Operational Policy Slots** are empty, so that Hermes does not invent policy.
9. As an **Unmatched Caller** sending product media, I want public catalog guidance without live price or inventory, so that account-scoped pricing is not leaked.
10. As a **Verified Customer** sending product media, I want live price and inventory in the same reply when Shopify is available, so that I can decide quickly.
11. As a **Verified Customer**, I want **Prior Order Product Reference** resolved when recent orders uniquely identify one SKU, so that I do not re-describe the product.
12. As a **Verified Customer** with ambiguous recent orders, I want disambiguation before media is sent, so that the wrong product is not shown.
13. As a **Verified Customer**, I want a governed response when Shopify is unavailable, so that Hermes does not fabricate catalog data.
14. As a **Non-Customer Contact** from government, I want urgent non-customer intake without account disclosure, so that regulatory traffic is routed correctly.
15. As a **Non-Customer Contact** supplier, I want invoice or delivery-exception language to uplift urgency, so that supplier issues are prioritized appropriately.
16. As a **Sales Outreach** sender, I want a brief decline and audit case, so that spam sales are logged without engagement.
17. As a **Named Recipient Request** contact, I want intake without employee directory leaks, so that internal staff privacy is protected.
18. As a **Non-Customer Contact** with general intent, I want governed non-customer intake from published policy, so that Hermes does not improvise rules.
19. As a customer texting **STOP**, I want opt-out processed at the gateway without running the full agent, so that compliance is immediate.
20. As a customer in a new **SMS Session**, I want a brief **SMS Session Opener** on the first reply, so that I know I am speaking with Toee AI support.
21. As a customer stating an explicit durable preference, I want Hermes to remember it via **Customer Memory**, so that I am not asked again unnecessarily.
22. As a returning **Verified Customer**, I want injected **Customer Memory** honored in replies, so that stated preferences persist across sessions.
23. As any customer, I want Hermes not to infer preferences into **Customer Memory**, so that memory stays explicit and governed.

### Customer Service Rep (Copilot)

24. As a **Customer Service Rep**, I want to log into **Copilot Workbench**, so that I can work **Human Intervention Cases**.
25. As a **Customer Service Rep**, I want a **Case Queue** with urgency and contact reason, so that I can prioritize work.
26. As a **Customer Service Rep**, I want read-only **Case Thread Context** for the selected case’s SMS thread, so that I see customer history without editing it.
27. As a **Customer Service Rep**, I want **Copilot Gateway** idle until I select a case, so that I do not accidentally run copilot in the wrong context.
28. As a **Customer Service Rep**, I want **Copilot Draft Action** for SMS replies on claimed cases, so that I can review AI drafts before send.
29. As a **Customer Service Rep**, I want employee-confirmed governed Textline send from the workbench, so that outbound SMS stays audited and policy-bound.
30. As a **Customer Service Rep**, I want to claim, assign, update priority, update contact reason, and resolve cases, so that case workflow is complete in v1.
31. As a **Customer Service Rep**, I want audit visibility for my workbench actions, so that accountability exists.
32. As a **Customer Service Rep**, I want queue filters for workload views, so that I can focus on urgent or unassigned cases.
33. As a **Customer Service Rep**, I want governed reads of Shopify, QBO, EasyRoutes, and knowledge through copilot, so that I can assist cases with the same tools as external service within profile limits.

### Workbench Supervisor / Admin

34. As a **Workbench Supervisor**, I want a separate **Admin Governance Console** entry from Copilot, so that governance and case work stay profile-separated.
35. As a **Workbench Supervisor**, I want `/admin/knowledge` to manage **Required Operational Policy Slots**, so that policy can be drafted and published safely.
36. As a **Workbench Supervisor**, I want **Knowledge Gap Prompt** completion flows, so that empty slots are filled before customers rely on them.
37. As a **Workbench Supervisor**, I want `submit_for_eval` and `promote_pending_policy` tied to eval, so that policy publish is gated.
38. As a **Workbench Supervisor**, I want `/admin/eval` to review **Launch Eval Report** runs, so that I can sign off medium failures and block bad releases.
39. As a **Workbench Supervisor**, I want `/admin/accounts` to manage **Workbench Account** roles, so that access control is centralized.
40. As a **Workbench Supervisor**, I want rollback of published operational policy, so that bad publishes can be reversed.
41. As a **Workbench Supervisor**, I want read-only case and audit visibility from admin routes when reviewing governance, so that evidence is available without customer-send tools.

### Platform / operations

42. As **DevOps**, I want separate Cloud Run services for workbench and gateway, so that public ingress and internal admin have distinct security boundaries.
43. As **DevOps**, I want Textline webhook signature verification, so that unsigned traffic is rejected.
44. As **DevOps**, I want fast webhook ack and async agent execution, so that Textline timeouts are avoided.
45. As **DevOps**, I want protected internal agent-turn routes with OIDC in production, so that async jobs are not open endpoints.
46. As **DevOps**, I want per-phone soft rate limiting on SMS ingress, so that abuse is throttled.
47. As **DevOps**, I want structured gateway error classes and logging, so that incidents are diagnosable.
48. As **DevOps**, I want optional Composio Connected Account onboarding via ops runbook, so that Layer 1 integrations can switch from mock to live without workbench OAuth UI.
49. As **DevOps**, I want `pnpm eval` to run `text_first_launch` in CI, so that regressions are caught before deploy.
50. As a **developer**, I want mock-first local development without Composio credentials, so that onboarding to the repo is fast.
51. As a **developer**, I want pinned Hermes SDK version and upgrade workflow, so that Hermes upgrades stay controlled.
52. As a **developer**, I want only **Hermes Runtime Shim** importing official Hermes packages, so that upgrade boundaries stay thin.

## Implementation Decisions

### Deep modules to build

The implementation should favor **deep modules** with stable interfaces and isolated tests.

| Module | Responsibility | Stable interface |
|--------|----------------|------------------|
| **Launch Eval Runner** | Load fixtures, merge mocks, execute scenarios, emit JSON report, exit code on high severity | `runSuite(suite, options) => EvalReport` |
| **Adapter mock registry** | Provide deterministic responses for all v1 `toee_*` actions used in eval | `createMockAdapterRegistry(baseMocks, overrides)` |
| **Integration driver selector** | Choose `mock`, `composio`, or `rest` per Layer 1 tool from env | `resolveDriver(toolName) => Driver` |
| **Domain adapter dispatch** | Route `action` to implementation, enforce **Tool Gate**, shape fields, audit | `executeTool({ tool, action, context, input }) => ToolResult` |
| **Ingress phone match** | Synchronous gateway identity step before agent | `matchIngressPhone(phone) => IdentityMatchResult` |
| **Inbound channel normalizer** | Map Textline payload to **InboundChannelEvent** | `normalizeTextlineWebhook(payload) => InboundChannelEvent` |
| **Agent turn orchestration hook** | Persist **AgentTurnContext**, invoke **Hermes Runtime Shim** with external profile, enqueue async work | `enqueueAgentTurn(event) => ack`; `runAgentTurn(job) => TurnResult` |
| **Hermes runtime shim** | Boot SDK, register adapters, select profile, no custom orchestrator | `runProfileTurn({ profile, turnContext }) => AgentResult` |
| **Customer memory service** | Slot reads, provisional merge, governed upsert actions | `getInjectionBlock(identity)`; `upsertPreference(...)` |
| **Workbench session auth** | Username/password sessions, route-derived profile | `authenticate(credentials)`; `requireSession(request)` |
| **Workbench BFF mappers** | Resource routes to v1 adapter actions without exposing tool envelopes | REST handlers for `/api/auth`, `/api/copilot`, `/api/admin` |
| **Conversation entity store** | **CustomerThread**, **SmsSession**, **MessageTurn** persistence in **Hermes Native Memory** | CRUD aligned to ADR-0115 |

### Monorepo and deployment

- One repository with `apps/workbench`, `services/hermes-gateway`, `packages/domain-adapters`, `packages/hermes-runtime`, `packages/shared`, and `eval` runner package or script area per ADR-0091.
- Workbench never receives public Textline webhooks.
- Workbench and gateway both embed **Hermes Runtime Shim** in-process; workbench does not HTTP-call gateway for copilot/admin execution.
- Production secrets via GCP Secret Manager per ADR-0098.
- Demand-driven GCP services only when proven necessary per ADR-0025.

### Channel gateway (Textline)

- Verify webhook authenticity before agent processing.
- Normalize inbound events, run **Ingress Phone Match**, persist inbound state, return fast success, enqueue async agent job.
- **STOP** opt-out short-circuit at gateway without agent turn.
- Soft rate limit per phone number.
- Error classes: verify, normalize, identity, persist, enqueue with distinct HTTP outcomes per ADR-0104.
- Async execution via Cloud Tasks to protected internal route in production; dev may use in-memory queue with shared secret header.

### Hermes profiles and tools

- Implement v1 **External Customer Service Profile** tool allowlist and **Internal Copilot Profile** / **Supervisor Admin Profile** allowlists per ADR-0034, 0035, 0038, 0070.
- All business integrations expose one Hermes tool per domain with fixed `action` enums per ADR-0059.
- **Tool Gate** lives inside adapters and gateway, not prompt-only.
- Layer 1 tools (Shopify read, QBO read, Square payment link) ship with mock drivers first; composio drivers added at integration milestone per ADR-0132.
- EasyRoutes, Textline reply, identity lookup, case, customer memory, knowledge, workbench, and eval tools are custom adapters.

### Memory and conversation model

- Use **Hermes Native Memory** only; four layers: Identity Graph, conversation, operational, **Customer Memory** per ADR-0110.
- Entity hierarchy: **CustomerThread** → **SmsSession** → **MessageTurn**; cases reference threads per ADR-0115.
- Provisional customer memory merges on verified ingress per ADR-0112.
- Retention periods per ADR-0116 and ADR-0004 extension.

### Copilot Workbench UI

- `/copilot` default: left dual zone (**Case Queue** + read-only **Case Thread Context**), right **Copilot Gateway** idle until case selected.
- Governed Textline send: draft card, confirmation modal, claimed case only.
- Admin routes: `/admin/knowledge`, `/admin/eval`, `/admin/accounts` only in v1.
- Global shell, session handling, and dismissible error banner per workbench ADRs.
- Audit on separate route; CSR does not see admin nav.

### Launch Eval

- Execute `text_first_launch` scenarios 01–18 and 24–26 from repository YAML.
- Merge `eval/mocks/base.yaml` → identity preset → scenario overrides.
- Support behavioral, tool, disclosure, text, memory_assertions, and max_severity checks per ADR-0072 and ADR-0118.
- Write JSON report to `eval/reports/` per ADR-0074.
- `pnpm eval` default suite is `text_first_launch` per ADR-0121.
- High-severity failures block promotion.

### Composio (integration milestone)

- Composio is internal to adapters only per ADR-0127.
- Ops onboarding via `docs/ops/composio-connected-accounts.md`; no workbench integrations UI in v1.
- `INTEGRATION_DRIVER=mock` default; staging/production switch to composio after Connected Account link and smoke.

### Security and policy

- Workbench HttpOnly session auth; no bearer tokens in browser.
- No customer-facing Hermes channels initiate Composio OAuth.
- Policy enforcement layers: profile allowlist, **Tool Gate**, **Launch Eval Gate**, **Skill Guidance** supporting only per ADR-0033.
- English-only external customer service in v1.

### Delivery phases inside this PRD

1. **Foundation**: monorepo packages, shared types, hermes-runtime shim boot, mock adapter registry, eval runner green on fixtures.
2. **Gateway path**: Textline webhook → identity → persist → async agent → `toee_textline_reply`.
3. **Workbench path**: auth, case queue/thread, copilot draft, governed send, admin three routes.
4. **Memory and customer memory**: identity graph, thread hierarchy, injection and governed upsert.
5. **Integration hardening**: composio drivers for Layer 1, ops runbook smoke, staging gate.
6. **Go-live**: production env, eval pass, supervisor sign-off, Textline live traffic.

## Testing Decisions

### What makes a good test

- Test **observable behavior** at module boundaries: tool results, gate blocks, HTTP status codes, eval pass/fail, BFF response contracts.
- Do not assert internal Composio SDK call sequences or Hermes model wording beyond fixture `text` assertions in eval.
- Prefer deterministic mocks for external SaaS and Hermes model outputs in unit and eval tests.

### Modules to test (recommended)

| Module | Test type | Priority |
|--------|-----------|----------|
| **Launch Eval Runner** | Fixture-driven integration tests; one test per scenario id or representative subset | **P0** |
| **Adapter Tool Gate** | Unit tests per tool/action for verified, unmatched, ambiguous, email-link failure | **P0** |
| **Ingress phone match** | Unit tests for single, zero, multi match | **P0** |
| **Inbound normalizer** | Unit tests for Textline payload → event shape | **P0** |
| **Gateway webhook pipeline** | Integration tests: signature fail 401, STOP short-circuit, ack + enqueue | **P0** |
| **Customer memory merge/injection** | Unit tests for provisional→verified and slot honor | **P1** |
| **Workbench BFF auth** | Integration tests for session and role gates | **P1** |
| **Hermes runtime shim** | Smoke test with mock adapters registered | **P1** |
| **Composio drivers** | Staging manual smoke per ops runbook; minimal contract tests with mocked Composio client | **P2** |
| **Workbench UI** | Selective e2e for login, case select, draft flow later | **P2** |

### Prior art

- Repository already defines expected behavior in `eval/scenarios/*.yaml`; the runner tests are the authoritative regression suite for external profile behavior.
- ADR-0010 and ADR-0117 define minimum scenario coverage.

## Out of Scope

- **Voice Layer** (Net2phone, Twilio ConversationRelay, **Personalized Opening Greeting**)
- **Email channel** implementation and `email_go_live` eval execution as a go-live gate (fixtures exist; channel not built)
- Web chat and outbound campaigns
- Workbench `/admin/integrations` or in-product Composio OAuth UI
- Exposing Composio toolkits directly to Hermes agents
- Business-system write tools beyond governed employee-confirmed Textline send
- Supervisor Admin customer-facing send tools
- Multi-tenant Composio or per-customer Connected Accounts
- Merged cross-channel Copilot timeline in v1
- Autonomous Copilot customer sends without employee confirmation
- Full operational policy content authoring (structure and publish flow are in scope; business copy is filled via KnowledgeOps)
- GDPR erasure automation (manual cross-system process in v1)
- Local Chrome CDP production crawl paths

## Further Notes

- **email_go_live** fixtures and ADRs are preserved for a later PRD.
- Hermes version bumps require eval regression and ADR note per ADR-0101.
- After this PRD ships, use the long-term roadmap issue or doc for Voice, Email, and Copilot governed-write expansion phases.
- Existing partial scaffold under `apps/workbench` and `packages/shared` should be extended, not replaced ad hoc.
