# Hermes VA Long-Term Roadmap (post Text-First Launch)

This roadmap assumes successful delivery of the **Text-First Launch** PRD: Textline SMS go-live with **Launch Eval Gate**, **Copilot Workbench**, **Admin Governance Console**, mock-first adapters, and optional Composio Layer 1 cutover.

Phases are sequential gates. Each phase should have its own eval suite pass and ADR updates where boundaries change.

---

## Phase 0 — Text-First Launch (current PRD)

**Goal:** Production Textline SMS on **External Customer Service Profile**.

**Deliverables:**
- Monorepo scaffold (workbench, gateway, shared, domain-adapters, hermes-runtime, eval runner)
- Textline webhook → identity → async agent → reply
- Case + Copilot + Admin three routes
- Customer Memory v1
- `text_first_launch` eval green in CI/staging
- Composio staging smoke (optional before prod cutover)

**Exit gate:** No high-severity **Launch Eval Report** failures; supervisor sign-off; production Textline traffic.

---

## Phase 1 — Integration hardening & observability

**Goal:** Operate Text-First reliably in production.

**Deliverables:**
- Production Composio Connected Accounts per ops runbook
- Cloud Logging alerts for `auth_expired`, gateway error classes, eval regressions
- Runbook drills: reconnect, API key rotation
- Weekly **Knowledge Crawl** job on schedule (ADR-0001, ADR-0030)
- **Shopify Knowledge Sync** + operational policy publish rhythm
- Hermes pin upgrade process exercised once in staging

**Exit gate:** 30-day stable SMS operations; medium eval failures documented; on-call can reconnect Composio without code change.

---

## Phase 2 — Copilot governed-write expansion

**Goal:** Reduce employee manual work while keeping confirmation and **Tool Gate**.

**Deliverables:**
- Harden employee-confirmed Textline send patterns from Phase 0
- Expand **Copilot Draft Action** coverage (email draft, internal note polish)
- Additional **Human Intervention Case** automation assists (priority suggestions, contact reason hints) without autonomous customer sends
- Workbench performance and queue ergonomics from production feedback

**Exit gate:** Supervisor-approved governed-write ADRs; eval scenarios for any new copilot write paths.

---

## Phase 3 — Voice Layer

**Goal:** Add phone channel on validated text core (ADR-0012 phase 2).

**Deliverables:**
- Net2phone **Hermes Transfer Rule** integration (after-hours, no-answer)
- Twilio ConversationRelay ingress
- **Personalized Opening Greeting** with disclosure limits
- **Ingress Phone Match** shared with SMS rules
- Voice-specific **Launch Eval** scenarios (extend ADR-0010)
- Copilot presentation for voice-originated cases (channel threads separate per ADR-0058)

**Exit gate:** Voice eval pass; no wrongful disclosure on verified/unmatched/ambiguous callers; SMS regression unchanged.

---

## Phase 4 — Email channel go-live

**Goal:** Governed email customer service (ADR-0051–0057, email ADRs 0122–0126).

**Deliverables:**
- Email **Channel Gateway** (inbound parse, **From-only** sender match)
- **Email Thread** continuity with per-message rematch
- **Email Support Signature** on every outbound
- Governed email reply tool (`toee_email_*` ADR-first) with optional Composio Gmail/Outlook internal driver
- `email_go_live` eval pass (scenarios 14–18 email + 19–23)
- Non-customer parity on email fixtures

**Exit gate:** `email_go_live` suite green; staging email smoke; no Registered Phone language on email unmatched paths.

---

## Phase 5 — Web chat & campaign surfaces (if prioritized)

**Goal:** Additional async text channels on same **Hermes Core**.

**Deliverables:**
- Web chat ingress adapter and session model ADR
- Campaign/outbound constraints ADR (consent, opt-out parity)
- Channel-specific eval fixtures
- Copilot thread presentation updates per channel rules

**Exit gate:** Channel-specific eval; shared Tool Gate unchanged.

---

## Phase 6 — Admin & governance maturity

**Goal:** Lower ops toil; optional workbench integrations UX.

**Deliverables:**
- Optional `/admin/integrations` for Composio status (if ADR approves)
- Scheduled Composio health job (if alert noise justifies)
- Richer eval analytics in `/admin/eval`
- Policy publish automation and rollback drills
- Account lifecycle improvements

**Exit gate:** ADR per new admin surface; no widening of Supervisor Admin to customer send tools.

---

## Phase 7 — Business writes & deeper ERP actions (strictly gated)

**Goal:** Only where eval + policy + Tool Gate prove safe.

**Deliverables:**
- New write-tool ADRs (never Composio-direct to agent)
- Expanded QBO/Shopify actions behind `toee_*` enums
- Additional **Copilot Governed Write** phases with employee confirmation
- Financially sensitive eval scenarios

**Exit gate:** Separate publish eval per write tool; legal/ops sign-off.

---

## Cross-cutting tracks (all phases)

| Track | Continues across phases |
|-------|-------------------------|
| **Launch Eval Gate** | Re-run on model, prompt, policy, Hermes upgrade |
| **Hermes native-first** | Thin shim; remove local workarounds on upstream capability |
| **ADR-first integrations** | Composio or REST behind new `toee_*` tools only |
| **CONTEXT + ADR hygiene** | Glossary in CONTEXT; hard decisions in ADR |
| **Retention & compliance** | ADR-0004 periods applied in memory layers |

---

## Suggested issue breakdown after PRD

For agent execution, child issues may follow module boundaries:

1. Eval runner + mock adapter registry (P0)
2. Hermes runtime shim + external profile boot
3. Domain adapters: identity, case, memory, knowledge
4. Domain adapters: shopify, qbo, easyroutes, textline, square (mock drivers)
5. Gateway: Textline pipeline + async agent turn
6. Workbench: auth + BFF skeleton
7. Workbench: Copilot UI + governed send
8. Workbench: Admin three routes
9. Composio Layer 1 drivers + staging smoke
10. CI: `pnpm eval` gate on PR

---

## Explicitly not on roadmap until re-approved

- Customer-facing Composio OAuth
- Agent-direct vendor toolkit exposure
- Parallel phone + SMS launch
- Custom agent orchestrator or non-Hermes memory store
- Multi-merchant Composio tenancy
